// Copyright (c) 2026 IQ.Pilot.
#include "tools/cabana/ui/auth.h"

#include <cerrno>
#include <csignal>
#include <fcntl.h>
#include <poll.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
#ifdef __APPLE__
#include <crt_externs.h>
#endif

std::string authenticateKonn3kt(const std::string &provider, std::atomic<bool> *abort) {
  int output[2];
#ifdef __linux__
  if (pipe2(output, O_CLOEXEC) != 0) return {};
#else
  if (pipe(output) != 0) return {};
  if (fcntl(output[0], F_SETFD, FD_CLOEXEC) != 0 || fcntl(output[1], F_SETFD, FD_CLOEXEC) != 0) {
    close(output[0]);
    close(output[1]);
    return {};
  }
#endif
  posix_spawn_file_actions_t actions;
  int error = posix_spawn_file_actions_init(&actions);
  const bool initialized = error == 0;
#if defined(__APPLE__) && __MAC_OS_X_VERSION_MIN_REQUIRED >= 260000
  if (!error) error = posix_spawn_file_actions_addchdir(&actions, CABANA_ROOT);
#else
  if (!error) error = posix_spawn_file_actions_addchdir_np(&actions, CABANA_ROOT);
#endif
  if (!error) error = posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
  if (!error) error = posix_spawn_file_actions_adddup2(&actions, output[1], STDOUT_FILENO);
  if (!error) error = posix_spawn_file_actions_addclose(&actions, output[0]);
  if (!error) error = posix_spawn_file_actions_addclose(&actions, output[1]);
  const char *args[] = {CABANA_PYTHON, "-m", "iqpilot.tools.lib.auth", provider.c_str(), "--json", nullptr};
#ifdef __APPLE__
  char **environment = *_NSGetEnviron();
#else
  char **environment = environ;
#endif
  pid_t pid = -1;
  if (!error) error = posix_spawnp(&pid, args[0], &actions, nullptr, const_cast<char *const *>(args), environment);
  if (initialized) posix_spawn_file_actions_destroy(&actions);
  close(output[1]);
  if (error) {
    close(output[0]);
    return {};
  }

  std::string result;
  pollfd descriptor{output[0], POLLIN, 0};
  while (!*abort) {
    int ready = poll(&descriptor, 1, 100);
    if (ready < 0) {
      if (errno == EINTR) continue;
      break;
    }
    if (!ready) continue;
    char buffer[4096];
    ssize_t count = read(output[0], buffer, sizeof(buffer));
    if (count <= 0) break;
    result.append(buffer, count);
  }
  close(output[0]);
  if (*abort) kill(pid, SIGTERM);
  int status = 0;
  while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {}
  return !*abort && WIFEXITED(status) && WEXITSTATUS(status) == 0 ? result : std::string{};
}
