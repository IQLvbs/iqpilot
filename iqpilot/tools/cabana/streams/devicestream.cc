#include "tools/cabana/streams/devicestream.h"

#include <cassert>
#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstring>
#include <fcntl.h>
#include <filesystem>
#include <memory>
#include <string>
#include <thread>
#include <utility>
#include <unistd.h>
#include <sys/wait.h>

#include "cereal/services.h"
#include "tools/cabana/utils/util.h"



DeviceStream::DeviceStream(Mode mode, std::string address)
    : mode_(mode), address_(address.empty() ? "127.0.0.1" : std::move(address)) {
}

DeviceStream::~DeviceStream() {
  stop();
  stopBridge();
}

void DeviceStream::stopBridge() {
  if (bridge_pid <= 0) return;

  ::kill(bridge_pid, SIGTERM);
  for (int i = 0; i < 30; ++i) {
    int status = 0;
    pid_t r = ::waitpid(bridge_pid, &status, WNOHANG);
    if (r == bridge_pid || (r < 0 && errno == ECHILD)) {
      bridge_pid = -1;
      return;
    }
    usleep(100000);
  }
  ::kill(bridge_pid, SIGKILL);
  ::waitpid(bridge_pid, nullptr, 0);
  bridge_pid = -1;
}

void DeviceStream::start() {
  if (mode_ == Mode::Bridge) {
    stopBridge();
    const std::string path = (executableDir() / "../../cereal/messaging/bridge").lexically_normal().string();
    const char *can_filter = "/\"can/\"";



    int err_pipe[2] = {-1, -1};
    if (::pipe(err_pipe) != 0) {
      error(std::string("Failed to start bridge: ") + strerror(errno));
      return;
    }

    pid_t pid = ::fork();
    if (pid == 0) {
      ::close(err_pipe[0]);
      ::fcntl(err_pipe[1], F_SETFD, FD_CLOEXEC);
      execl(path.c_str(), path.c_str(), address_.c_str(), can_filter, static_cast<char *>(nullptr));
      const int err = errno;
      (void)!::write(err_pipe[1], &err, sizeof(err));
      _exit(127);
    }

    ::close(err_pipe[1]);
    if (pid < 0) {
      ::close(err_pipe[0]);
      error(std::string("Failed to start bridge: ") + strerror(errno));
      return;
    }

    int exec_errno = 0;
    const ssize_t n = ::read(err_pipe[0], &exec_errno, sizeof(exec_errno));
    ::close(err_pipe[0]);
    if (n == static_cast<ssize_t>(sizeof(exec_errno))) {

      int status = 0;
      ::waitpid(pid, &status, 0);
      error(std::string("Failed to start bridge: ") + strerror(exec_errno));
      return;
    }

    bridge_pid = pid;
  }

  LiveStream::start();
}

void DeviceStream::streamThread() {
  mode_ == Mode::Zmq ? setenv("ZMQ", "1", 1) : unsetenv("ZMQ");
  const std::string socket_address = mode_ == Mode::Zmq ? address_ : "127.0.0.1";

  std::unique_ptr<Context> context(Context::create());
  std::unique_ptr<SubSocket> sock(SubSocket::create(context.get(), "can", socket_address, false, true, services.at("can").queue_size));
  assert(sock != NULL);

  while (!exit_) {
    std::unique_ptr<Message> msg(sock->receive(true));
    if (!msg) {
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
      continue;
    }
    handleEvent(kj::ArrayPtr<capnp::word>((capnp::word*)msg->getData(), msg->getSize() / sizeof(capnp::word)));
  }
}
