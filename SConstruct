import os
import subprocess
import sys
import sysconfig
import platform
import shlex
import numpy as np

import iqdbc
import msgq as msgq_package
import panda
import tinygrad

import SCons.Errors

SCons.Warnings.warningAsException(True)

# scons only auto-loads a site dir named site_scons at the repo root; ours lives under tools/,
# so replicate what _load_site_scons_dir does (sys.path for site_tools imports + run site_init)
SITE_DIR = Dir('#iqpilot/tools/scons').abspath
if SITE_DIR not in sys.path:
  sys.path.insert(0, SITE_DIR)
import site_init  # noqa: F401

# capnp's kj library warns when $PWD is stale (doesn't match the real cwd); keep them in sync
os.environ.pop('PWD', None)

Decider('MD5' if os.uname().machine == 'aarch64' else 'MD5-timestamp')

SetOption('num_jobs', max(1, int(os.cpu_count()/2)))

AddOption('--asan', action='store_true', help='turn on ASAN')
AddOption('--ubsan', action='store_true', help='turn on UBSan')
AddOption('--mutation', action='store_true', help='generate mutation-ready code')
AddOption('--ccflags', action='store', type='string', default='', help='pass arbitrary flags over the command line')
AddOption('--minimal',
          action='store_false',
          dest='extras',
          default=os.path.exists(File('#.gitattributes').abspath), # minimal by default on release branch (where there's no LFS)
          help='the minimum IQ.Pilot build. no tests, tools, etc.')
AddOption('--verbose', action='store_true', help='show full compiler/linker command lines instead of short build lines')

python_paths = [
  Dir("#").abspath,
]
for p in reversed(python_paths):
  if p not in sys.path:
    sys.path.insert(0, p)

if external_pythonpath := os.environ.get("PYTHONPATH"):
  python_paths += [p for p in external_pythonpath.split(os.pathsep) if p and p not in python_paths]

# Detect platform
arch = subprocess.check_output(["uname", "-m"], encoding='utf8').rstrip()
if platform.system() == "Darwin":
  arch = "Darwin"
  brew_prefix = subprocess.check_output(['brew', '--prefix'], encoding='utf8').strip()
elif arch == "aarch64" and os.path.isfile('/TICI'):
  arch = "larch64"
  try:
    from iqpilot.system.hardware import HARDWARE
    HARDWARE.set_power_save(False)
    os.sched_setaffinity(0, range(8))
  except Exception:
    # host tuning needs real device sysfs; the prebuilt arm64 container fakes /TICI and has none
    pass
assert arch in [
  "larch64",  # linux tici arm64
  "aarch64",  # linux pc arm64
  "x86_64",   # linux pc x64
  "Darwin",   # macOS arm64 (x86 not supported)
]

# ffmpeg comes from the system (brew on macOS, distro packages elsewhere) rather than
# a vendored wheel, so it always needs the static-link deps. Exported so tools/ can
# take upstream's `ffmpeg_libs` form instead of hand-listing codecs per SConscript.
ffmpeg_libs = ['avformat', 'avcodec', 'avutil', 'x264', 'z']
if arch != "Darwin":
  ffmpeg_libs += ['va', 'va-drm', 'drm']

env = Environment(
  ENV={
    "PATH": os.environ['PATH'],
    "PYTHONPATH": os.pathsep.join(python_paths + [Dir(f"#iqpilot/third_party/acados").abspath]),
    "ACADOS_SOURCE_DIR": Dir("#iqpilot/third_party/acados").abspath,
    "ACADOS_PYTHON_INTERFACE_PATH": Dir("#iqpilot/third_party/acados/acados_template").abspath,
    "TERA_PATH": Dir("#").abspath + f"/iqpilot/third_party/acados/{arch}/t_renderer"
  },
  CC='clang',
  CXX='clang++',
  CCFLAGS=[
    "-g",
    "-fPIC",
    "-O2",
    "-Wunused",
    "-Werror",
    "-Wshadow",
    "-Wno-unknown-warning-option",
    "-Wno-inconsistent-missing-override",
    "-Wno-c99-designator",
    "-Wno-reorder-init-list",
    "-Wno-vla-cxx-extension",
  ],
  CFLAGS=["-std=gnu11"],
  CXXFLAGS=["-std=c++1z"],
  CPPPATH=[
    "#",
    "#iqpilot",
    iqdbc.INCLUDE_PATH,
    msgq_package.INCLUDE_PATH,
    panda.INCLUDE_PATH,
    "#iqpilot/cereal/gen/cpp",
    "#iqpilot/third_party",
    "#iqpilot/third_party/json11",
    "#iqpilot/third_party/linux/include",
    "#iqpilot/third_party/acados/include",
    "#iqpilot/third_party/acados/include/blasfeo/include",
    "#iqpilot/third_party/acados/include/hpipm/include",
    "#iqpilot/third_party/catch2/include",
    "#iqpilot/third_party/libyuv/include",
  ],
  LIBPATH=[
    "#iqpilot/common",
    "#iqpilot/third_party",
    "#iqpilot/selfdrive/pandad",
    f"#iqpilot/third_party/libyuv/{arch}/lib",
    f"#iqpilot/third_party/acados/{arch}/lib",
  ],
  RPATH=[],
  CYTHONCFILESUFFIX=".cpp",
  COMPILATIONDB_USE_ABSPATH=True,
  tools=["default", "cython", "compilation_db"],
  toolpath=["#iqpilot/tools/scons/site_tools"],
)

# Arch-specific flags and paths
if arch == "larch64":
  env.Append(CPPPATH=[
    "#iqpilot/third_party/opencl/include",
    "/usr/include/aarch64-linux-gnu",
  ])
  env.Append(LIBPATH=[
    "/usr/local/lib",
    "/usr/lib/aarch64-linux-gnu",
    "/system/vendor/lib64",
  ])
  arch_flags = ["-D__TICI__", "-mcpu=cortex-a57", "-DQCOM2"]
  env.Append(CCFLAGS=arch_flags)
  env.Append(CXXFLAGS=arch_flags)
elif arch == "Darwin":
  env.Append(LIBPATH=[
    f"{brew_prefix}/lib",
    f"{brew_prefix}/opt/openssl@3.0/lib",
    f"{brew_prefix}/opt/llvm/lib/c++",
    "/System/Library/Frameworks/OpenGL.framework/Libraries",
  ])
  env.Append(CCFLAGS=["-DGL_SILENCE_DEPRECATION"])
  env.Append(CXXFLAGS=["-DGL_SILENCE_DEPRECATION"])
  env.Append(CPPPATH=[
    f"{brew_prefix}/include",
    f"{brew_prefix}/opt/openssl@3.0/include",
  ])
  # the same static libs are pulled in by multiple deps; harmless, quiet the noise
  env.Append(LINKFLAGS=["-Wl,-no_warn_duplicate_libraries"])
  # spi.cc is device-only, so it archives with no symbols on host. 'ar rcS' skips the
  # symbol table (no warning) and ranlib rebuilds it quietly with -no_warning_for_no_symbols.
  env.Replace(ARFLAGS="rcS")
  env.Append(RANLIBFLAGS=["-no_warning_for_no_symbols"])
else:
  env.Append(LIBPATH=[
    "/usr/lib",
    "/usr/local/lib",
  ])

# Sanitizers and extra CCFLAGS from CLI
if GetOption('asan'):
  env.Append(CCFLAGS=["-fsanitize=address", "-fno-omit-frame-pointer"])
  env.Append(LINKFLAGS=["-fsanitize=address"])
elif GetOption('ubsan'):
  env.Append(CCFLAGS=["-fsanitize=undefined"])
  env.Append(LINKFLAGS=["-fsanitize=undefined"])

_extra_cc = shlex.split(GetOption('ccflags') or '')
if _extra_cc:
  env.Append(CCFLAGS=_extra_cc)

# no --as-needed on mac linker
if arch != "Darwin":
  env.Append(LINKFLAGS=["-Wl,--as-needed", "-Wl,--no-undefined"])

# pretty build output (short colored lines; pass --verbose for full commands)
env.Tool('pretty')

# progress output
node_interval = 5
node_count = 0
def progress_function(node):
  global node_count
  node_count += node_interval
  sys.stderr.write("progress: %d\n" % node_count)
if os.environ.get('SCONS_PROGRESS'):
  Progress(progress_function, interval=node_interval)

# ********** Cython build environment **********
py_include = sysconfig.get_paths()['include']
envCython = env.Clone()
envCython["CPPPATH"] += [py_include, np.get_include()]
envCython["CCFLAGS"] += ["-Wno-#warnings", "-Wno-shadow", "-Wno-deprecated-declarations"]
envCython["CCFLAGS"].remove("-Werror")

envCython["LIBS"] = []
if arch == "Darwin":
  envCython["LINKFLAGS"] = env["LINKFLAGS"] + ["-bundle", "-undefined", "dynamic_lookup"]
else:
  envCython["LINKFLAGS"] = ["-pthread", "-shared"]

np_version = SCons.Script.Value(np.__version__)
Export('envCython', 'np_version')

tinygrad_dir = os.path.dirname(tinygrad.__file__)
Export('env', 'arch', 'ffmpeg_libs', 'tinygrad_dir')

# Setup cache dir
default_cache_dir = os.environ.get('SCONS_CACHE_DIR') or ('/data/scons_cache' if arch == "larch64" else '/tmp/scons_cache')
cache_dir = ARGUMENTS.get('cache_dir', default_cache_dir)
CacheDir(cache_dir)
Clean(["."], cache_dir)

# ********** start building stuff **********

# Build common module
SConscript(['iqpilot/common/SConscript'])
Import('_common')
common = [_common, 'json11', 'zmq']
Export('common')

msgq = File(msgq_package.LIB_PATH)
visionipc = File(msgq_package.VISIONIPC_LIB_PATH)
msgq_python = File(msgq_package.PYTHON_LIB_PATH)
Export('msgq', 'visionipc', 'msgq_python')

SConscript(['iqpilot/cereal/SConscript'])

Import('socketmaster')
messaging = [socketmaster, msgq, 'capnp', 'kj',]
Export('messaging')

# Build system services
SConscript([
  'iqpilot/system/loggerd/SConscript',
  'iqpilot/system/proprietary_runtime/SConscript',
])

if arch == "larch64":
  SConscript(['iqpilot/system/camerad/SConscript'])

# Build openpilot
SConscript(['iqpilot/third_party/SConscript'])

SConscript(['iqpilot/selfdrive/SConscript'])

SConscript(['iqpilot/SConscript'])

if Dir('#iqpilot/tools/cabana/').exists() and GetOption('extras'):
  SConscript(['iqpilot/tools/replay/SConscript'])
  if arch != "larch64":
    SConscript(['iqpilot/tools/cabana/SConscript'])
    if Dir('#iqpilot/tools/jotpluggler/').exists():
      SConscript(['iqpilot/tools/jotpluggler/SConscript'])


env.CompilationDatabase('compile_commands.json')
