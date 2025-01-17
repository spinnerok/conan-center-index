from conan.tools.cmake import CMakeToolchain, CMake
from conan.tools.microsoft import is_msvc, is_msvc_static_runtime
from conan.tools.build import check_min_cppstd
from conan.tools.files import copy, get, patch, save, rm, rmdir
from conan.tools.scm import Version
from conan.errors import ConanInvalidConfiguration
from conan import ConanFile
import functools
import os
import textwrap

required_conan_version = ">=1.45.0"


class Antlr4CppRuntimeConan(ConanFile):
    name = "antlr4-cppruntime"
    homepage = "https://github.com/antlr/antlr4/tree/master/runtime/Cpp"
    description = "C++ runtime support for ANTLR (ANother Tool for Language Recognition)"
    topics = ("antlr", "parser", "runtime")
    url = "https://github.com/conan-io/conan-center-index"
    license = "BSD-3-Clause"
    options = {
        "shared": [True, False],
        "fPIC": [True, False],
    }
    default_options = {
        "shared": False,
        "fPIC": True,
    }
    settings = "os", "compiler", "build_type", "arch"
    short_paths = True

    compiler_required_cpp17 = {
        "Visual Studio": "16",
        "gcc": "7",
        "clang": "5",
        "apple-clang": "9.1"
    }


    @property
    def _source_subfolder(self):
        return "source_subfolder"

    def export_sources(self):
        copy(self, "CMakeLists.txt", src=self.recipe_folder, dst=self.export_sources_folder)
        for obj in self.conan_data.get("patches", {}).get(self.version, []):
            copy(self, obj["patch_file"], src=self.recipe_folder, dst=self.export_sources_folder)

    def config_options(self):
        if self.settings.os == "Windows":
            del self.options.fPIC

    def configure(self):
        if self.options.shared:
            del self.options.fPIC

    def requirements(self):
        self.requires("utfcpp/3.2.1")
        if self.settings.os in ("FreeBSD", "Linux"):
            self.requires("libuuid/1.0.3")

    def validate(self):
        compiler = self.settings.compiler
        compiler_version = Version(self.settings.compiler.version)
        antlr_version = Version(self.version)

        if compiler == "Visual Studio" and compiler_version < "16":
            raise ConanInvalidConfiguration("library claims C2668 'Ambiguous call to overloaded function'")
            # Compilation of this library on version 15 claims C2668 Error.
            # This could be Bogus error or malformed Antl4 libary.
            # Version 16 compiles this code correctly.

        if antlr_version >= "4.10":
            # Antlr4 for 4.9.3 does not require C++17 - C++11 is enough.
            # for newest version we need C++17 compatible compiler here

            if self.settings.get_safe("compiler.cppstd"):
                check_min_cppstd(self, "17")

            minimum_version = self.compiler_required_cpp17.get(str(self.settings.compiler), False)
            if minimum_version:
                if compiler_version < minimum_version:
                    raise ConanInvalidConfiguration(f"{self.name} requires C++17, which your compiler does not support.")
            else:
                self.output.warn(f"{self.name} requires C++17. Your compiler is unknown. Assuming it supports C++17.")

        if is_msvc(self) and antlr_version == "4.10":
            raise ConanInvalidConfiguration(f"{self.name} Antlr4 4.10 version is broken on msvc - Use 4.10.1 or above.")

    def build_requirements(self):
        if self.settings.os in ("FreeBSD", "Linux"):
            self.build_requires("pkgconf/1.7.4")

    def source(self):
        get(self, **self.conan_data["sources"][self.version],
                  destination=self._source_subfolder, strip_root=True)

    def _patch_sources(self):
        for obj in self.conan_data.get("patches", {}).get(self.version, []):
            patch(**obj)

    def generate(self):
        tc = CMakeToolchain(self)
        tc.variables["ANTLR4_INSTALL"] = True
        tc.variables["WITH_LIBCXX"] = self.settings.compiler.get_safe("libcxx") == "libc++"
        tc.variables["ANTLR_BUILD_CPP_TESTS"] = False
        if is_msvc(self):
            tc.variables["WITH_STATIC_CRT"] = is_msvc_static_runtime(self)
        tc.variables["WITH_DEMO"] = False
        tc.generate()

    @functools.lru_cache(1)
    def _configure_cmake(self):
        cmake = CMake(self)
        cmake.configure()
        return cmake

    def build(self):
        self._patch_sources()
        cmake = self._configure_cmake()
        cmake.build()

    def package(self):
        copy(self, "LICENSE.txt", src=self._source_subfolder, dst=os.path.join(self.package_folder, "licenses"))
        cmake = self._configure_cmake()
        cmake.install()
        if self.options.shared:
            rm(self, "*antlr4-runtime-static.*", os.path.join(self.package_folder, "lib"))
            rm(self, "*antlr4-runtime.a", os.path.join(self.package_folder, "lib"))
        else:
            rm(self, "*.dll", os.path.join(self.package_folder, "bin"))
            rm(self, "antlr4-runtime.lib", os.path.join(self.package_folder, "lib"))
            rm(self, "*antlr4-runtime.so*", os.path.join(self.package_folder, "lib"))
            rm(self, "*antlr4-runtime.dll*", os.path.join(self.package_folder, "lib"))
            rm(self, "*antlr4-runtime.*dylib", os.path.join(self.package_folder, "lib"))
        rmdir(self, path=os.path.join(self.package_folder, "share"))

        # FIXME: this also removes lib/cmake/antlr4-generator
        # This cmake config script is needed to provide the cmake function `antlr4_generate`
        rmdir(self, path=os.path.join(self.package_folder, "lib", "cmake"))

        # TODO: to remove in conan v2 once cmake_find_package* generatores removed
        self._create_cmake_module_alias_targets(
            os.path.join(self.package_folder, self._module_file_rel_path),
            {"antlr4_shared" if self.options.shared else "antlr4_static": "antlr4-cppruntime::antlr4-cppruntime"}
        )

    def _create_cmake_module_alias_targets(self, module_file, targets):
        content = ""
        for alias, aliased in targets.items():
            content += textwrap.dedent(f"""\
                if(TARGET {aliased} AND NOT TARGET {alias})
                    add_library({alias} INTERFACE IMPORTED)
                    set_property(TARGET {alias} PROPERTY INTERFACE_LINK_LIBRARIES {aliased})
                endif()
            """)
        save(self, path=module_file, content=content)

    @property
    def _module_file_rel_path(self):
        return os.path.join("lib", "cmake", f"conan-official-{self.name}-targets.cmake")

    def package_info(self):
        self.cpp_info.set_property("cmake_file_name", "antlr4-runtime")
        self.cpp_info.set_property("cmake_target_name", "antlr4_shared" if self.options.shared else "antlr4_static")
        libname = "antlr4-runtime"
        if is_msvc(self) and not self.options.shared:
            libname += "-static"
        self.cpp_info.libs = [libname]
        self.cpp_info.includedirs.append(os.path.join("include", "antlr4-runtime"))
        if self.settings.os == "Windows" and not self.options.shared:
            self.cpp_info.defines.append("ANTLR4CPP_STATIC")
        if self.settings.os in ("FreeBSD", "Linux"):
            self.cpp_info.system_libs = ["pthread"]

        # TODO: to remove in conan v2 once cmake_find_package* generatores removed
        self.cpp_info.filenames["cmake_find_package"] = "antlr4-runtime"
        self.cpp_info.filenames["cmake_find_package_multi"] = "antlr4-runtime"
        self.cpp_info.build_modules["cmake_find_package"] = [self._module_file_rel_path]
        self.cpp_info.build_modules["cmake_find_package_multi"] = [self._module_file_rel_path]
