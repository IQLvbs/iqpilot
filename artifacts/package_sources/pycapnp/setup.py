#!/usr/bin/env python
"""
pycapnp distutils setup.py
"""

import os
import shutil

from distutils.command.clean import clean as _clean

from setuptools import setup, Extension

_this_dir = os.path.dirname(__file__)

import subprocess
from pathlib import Path

MAJOR = 2
MINOR = 2
MICRO = 4
TAG = ".post1"
VERSION = "%d.%d.%d%s" % (MAJOR, MINOR, MICRO, TAG)


# Write version info
def write_version_py(filename=None):
    """
    Generate pycapnp version
    """
    cnt = """\
from .lib.capnp import _CAPNP_VERSION_MAJOR as LIBCAPNP_VERSION_MAJOR  # noqa: F401
from .lib.capnp import _CAPNP_VERSION_MINOR as LIBCAPNP_VERSION_MINOR  # noqa: F401
from .lib.capnp import _CAPNP_VERSION_MICRO as LIBCAPNP_VERSION_MICRO  # noqa: F401
from .lib.capnp import _CAPNP_VERSION as LIBCAPNP_VERSION  # noqa: F401

version = '%s'
short_version = '%s'
"""
    if not filename:
        filename = os.path.join(os.path.dirname(__file__), "capnp", "version.py")

    a = open(filename, "w")
    try:
        a.write(cnt % (VERSION, VERSION))
    finally:
        a.close()


write_version_py()

# Use the fork README as the package description
with open("README.md", encoding="utf-8") as f:
    long_description = f.read()


class clean(_clean):
    """
    Clean command, invoked with `python setup.py clean`
    """

    def run(self):
        _clean.run(self)
        for x in [
            os.path.join("capnp", "lib", "capnp.cpp"),
            os.path.join("capnp", "lib", "capnp.h"),
            os.path.join("capnp", "version.py"),
            "build",
        ]:
            print("removing %s" % x)
            try:
                os.remove(x)
            except OSError:
                shutil.rmtree(x, ignore_errors=True)


from Cython.Distutils import build_ext as build_ext_c  # noqa: E402


class build_libcapnp_ext(build_ext_c):
    """
    Build capnproto library
    """

    def run(self):
        source = Path(_this_dir, "vendor", "capnproto").resolve()
        build = Path(self.build_temp, "capnproto").resolve()
        args = [
            "cmake",
            "-S",
            str(source),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
        ]
        if os.environ.get("CMAKE_OSX_ARCHITECTURES"):
            args.append("-DCMAKE_OSX_ARCHITECTURES=" + os.environ["CMAKE_OSX_ARCHITECTURES"])
        if os.environ.get("MACOSX_DEPLOYMENT_TARGET"):
            args.append("-DCMAKE_OSX_DEPLOYMENT_TARGET=" + os.environ["MACOSX_DEPLOYMENT_TARGET"])
        subprocess.run(args, check=True)
        subprocess.run(["cmake", "--build", str(build), "--parallel", str(self.parallel or 2)], check=True)
        archive = str(build / "libcapnp-vendored.a")
        for extension in self.extensions:
            extension.include_dirs.insert(0, str(source / "src"))
            extension.extra_objects = [archive]
            extension.depends = [str(p) for p in source.rglob("*") if p.is_file()] + [archive]
        return build_ext_c.run(self)


extra_compile_args = ["-std=c++17", "-pthread"]
import Cython.Build  # noqa: E402
import Cython  # noqa: E402

extensions = [
    Extension(
        "*",
        [
            "capnp/helpers/exception.cpp",
            "capnp/lib/*.pyx",
        ],
        extra_compile_args=extra_compile_args,
        extra_link_args=["-pthread"],
        language="c++",
    )
]

setup(
    python_requires=">=3.12",
    name="pycapnp",
    packages=["capnp", "capnp.lib"],
    include_package_data=False,
    version=VERSION,
    package_data={
        "capnp": [
            "*.pxd",
            "*.h",
            "helpers/*.pxd",
            "helpers/*.h",
            "includes/*.h",
            "includes/*.pxd",
            "lib/*.pxd",
            "lib/*.py",
            "lib/*.pyx",
            "lib/*.h",
        ]
    },
    ext_modules=Cython.Build.cythonize(extensions),
    cmdclass={"clean": clean, "build_ext": build_libcapnp_ext},
    install_requires=[],
    # PyPi info
    description="A cython wrapping of the C++ Cap'n Proto library",
    long_description=long_description,
    long_description_content_type="text/markdown",
    license="BSD-2-Clause AND MIT",
    license_files=["LICENSE.md", "vendor/capnproto/LICENSE.txt"],
    # (setup.py only supports 1 author...)
    author="Jacob Alexander",  # <- Current maintainer; Original author -> Jason Paryani
    author_email="haata@kiibohd.com",
    url="https://git.konn3kt.com/IQ.Lvbs/pycapnp",
    download_url="https://git.konn3kt.com/IQ.Lvbs/pycapnp/archive/v%s.zip" % VERSION,
    keywords=["capnp", "capnproto", "Cap'n Proto", "pycapnp"],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX",
        "Programming Language :: C++",
        "Programming Language :: Cython",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        "Topic :: Communications",
    ],
)
