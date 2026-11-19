#include <zmq.h>

#include <iostream>

#include "catch2/catch.hpp"
#include "common/swaglog.h"
#include "common/util.h"
#include "system/hardware/hw.h"
#include "third_party/json11/json11.hpp"

#include "iqpilot/common/version.h"

std::string daemon_name = "testy";
std::string dongle_id = "test_dongle_id";
int LINE_NO = 0;

void log_thread(int thread_id, int msg_cnt) {
  for (int i = 0; i < msg_cnt; ++i) {
    LOGD("%d", thread_id);
    LINE_NO = __LINE__ - 1;
    usleep(1);
  }
}

void recv_log(void *sock, int thread_cnt, int thread_msg_cnt) {
  std::vector<int> thread_msgs(thread_cnt);
  int timeout_ms = 10000;
  REQUIRE(zmq_setsockopt(sock, ZMQ_RCVTIMEO, &timeout_ms, sizeof(timeout_ms)) == 0);

  for (int total_count = 0; total_count < thread_cnt * thread_msg_cnt; ++total_count) {
    char buf[4096] = {};
    REQUIRE(zmq_recv(sock, buf, sizeof(buf), 0) > 0);

    REQUIRE(buf[0] == CLOUDLOG_DEBUG);
    std::string err;
    auto msg = json11::Json::parse(buf + 1, err);
    REQUIRE(!msg.is_null());

    REQUIRE(msg["levelnum"].int_value() == CLOUDLOG_DEBUG);
    REQUIRE_THAT(msg["filename"].string_value(), Catch::Contains("test_swaglog.cc"));
    REQUIRE(msg["funcname"].string_value() == "log_thread");
    REQUIRE(msg["lineno"].int_value() == LINE_NO);

    auto ctx = msg["ctx"];

    REQUIRE(ctx["daemon"].string_value() == daemon_name);
    REQUIRE(ctx["dongle_id"].string_value() == dongle_id);
    REQUIRE(ctx["dirty"].bool_value() == true);

    REQUIRE(ctx["version"].string_value() == COMMA_VERSION);

    std::string device = Hardware::get_name();
    REQUIRE(ctx["device"].string_value() == device);

    int thread_id = atoi(msg["msg"].string_value().c_str());
    REQUIRE((thread_id >= 0 && thread_id < thread_cnt));
    thread_msgs[thread_id]++;
  }
  for (int i = 0; i < thread_cnt; ++i) {
    INFO("thread :" << i);
    REQUIRE(thread_msgs[i] == thread_msg_cnt);
  }
}

TEST_CASE("swaglog") {
  setenv("MANAGER_DAEMON", daemon_name.c_str(), 1);
  setenv("DONGLE_ID", dongle_id.c_str(), 1);
  setenv("dirty", "1", 1);
  const int thread_cnt = 5;
  const int thread_msg_cnt = 100;
  void *zctx = zmq_ctx_new();
  void *sock = zmq_socket(zctx, ZMQ_PULL);
  REQUIRE(zmq_bind(sock, Path::swaglog_ipc().c_str()) == 0);

  std::vector<std::thread> log_threads;
  for (int i = 0; i < thread_cnt; ++i) {
    log_threads.push_back(std::thread(log_thread, i, thread_msg_cnt));
  }
  for (auto &t : log_threads) t.join();

  recv_log(sock, thread_cnt, thread_msg_cnt);
  zmq_close(sock);
  zmq_ctx_destroy(zctx);
}
