#include <iostream>
#include <cassert>
#include <cerrno>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <chrono>
#include <algorithm>
#include <cstddef>
#include <cstdlib>
#include <mutex>
#include <random>
#include <string>
#include <limits>
#include <unordered_map>
#include <utility>
#include <vector>

#include <poll.h>
#include <pthread.h>
#ifdef __linux__
#include <sys/epoll.h>
#endif
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/un.h>
#include <fcntl.h>
#include <unistd.h>

#include <stdio.h>

#include "msgq/msgq.h"

uint64_t msgq_get_uid(void){
  std::random_device rd("/dev/urandom");
  std::uniform_int_distribution<uint64_t> distribution(1, (MSGQ_READER_WAITING >> 32) - 1);
  return distribution(rd) << 32;
}

static socklen_t wake_addr(uint64_t uid, sockaddr_un *addr) {
  memset(addr, 0, sizeof(*addr));
  addr->sun_family = AF_UNIX;
#ifdef __APPLE__
  snprintf(addr->sun_path, sizeof(addr->sun_path), "/tmp/msgq_wake_%016llx", (unsigned long long)uid);
  return sizeof(*addr);
#else
  int n = snprintf(addr->sun_path + 1, sizeof(addr->sun_path) - 1, "msgq_wake_%016llx", (unsigned long long)uid);
  return offsetof(sockaddr_un, sun_path) + 1 + n;
#endif
}

static int wake_socket() {
  int fd = socket(AF_UNIX, SOCK_DGRAM, 0);
  if (fd >= 0) {
    fcntl(fd, F_SETFD, FD_CLOEXEC);
    fcntl(fd, F_SETFL, O_NONBLOCK);
  }
  return fd;
}

struct WakeSender {
  int fd = -1;
  ~WakeSender() { if (fd >= 0) close(fd); }
};
static thread_local WakeSender t_sender;

#ifdef __linux__
// Edge-triggered so an undrained wake datagram can't turn the wait into a busy loop
struct PollSet {
  int epfd = -1;
  std::unordered_map<int, std::pair<const msgq_queue_t*, uint64_t>> regs;
  ~PollSet() { if (epfd >= 0) close(epfd); }
};
static thread_local PollSet t_pollset;
#endif

static void drop_wake_state_in_child() {
  if (t_sender.fd >= 0) close(t_sender.fd);
  t_sender.fd = -1;
#ifdef __linux__
  if (t_pollset.epfd >= 0) close(t_pollset.epfd);
  t_pollset.epfd = -1;
  t_pollset.regs.clear();
#endif
}

static void register_atfork_once() {
  static std::once_flag atfork_once;
  std::call_once(atfork_once, []() { pthread_atfork(nullptr, nullptr, drop_wake_state_in_child); });
}

static int wake_sender() {
  register_atfork_once();
  if (t_sender.fd < 0) t_sender.fd = wake_socket();
  return t_sender.fd;
}

static void wake_reader(uint64_t uid) {
  sockaddr_un addr;
  socklen_t len = wake_addr(uid, &addr);

  char c = 0;
  int fd = wake_sender();
  if (fd >= 0 && (sendto(fd, &c, sizeof(c), 0, reinterpret_cast<sockaddr*>(&addr), len) >= 0 ||
                  errno == ENOENT || errno == ECONNREFUSED)) {
    return;
  }

  // Unread datagrams count against the sending socket, so a stuck reader can fill it; retry on a fresh one
  int tmp = wake_socket();
  if (tmp < 0) return;
  sendto(tmp, &c, sizeof(c), MSG_DONTWAIT, reinterpret_cast<sockaddr*>(&addr), len);
  close(tmp);
}

static bool wake_socket_alive(uint64_t uid) {
  sockaddr_un addr;
  socklen_t len = wake_addr(uid & ~MSGQ_READER_WAITING, &addr);
  int fd = wake_socket();
  if (fd < 0) return true;
  int rc = connect(fd, reinterpret_cast<sockaddr*>(&addr), len);
  int err = errno;
  close(fd);
  return rc == 0 || (err != ECONNREFUSED && err != ENOENT);
}

static void wake_if_waiting(std::atomic<uint64_t> *read_uid, uint64_t new_value) {
  uint64_t old = read_uid->exchange(new_value);
  if (old & MSGQ_READER_WAITING) {
    wake_reader(old & ~MSGQ_READER_WAITING);
  }
}

static void close_wake_socket(msgq_queue_t *q) {
  if (q->wake_fd < 0) return;
  close(q->wake_fd);
  q->wake_fd = -1;
#ifdef __APPLE__
  sockaddr_un addr;
  wake_addr(q->read_uid_local, &addr);
  unlink(addr.sun_path);
#endif
}

static void bind_wake_socket(msgq_queue_t *q) {
  sockaddr_un addr;
  socklen_t len = wake_addr(q->read_uid_local, &addr);

  int fd = wake_socket();
  if (fd < 0) return;
  if (bind(fd, reinterpret_cast<sockaddr*>(&addr), len) < 0) {
    close(fd);
    return;
  }
  q->wake_fd = fd;
}

static void drain_wake_socket(int fd) {
  char c;
  recv(fd, &c, sizeof(c), MSG_DONTWAIT);
}

int msgq_msg_init_size(msgq_msg_t * msg, size_t size){
  msg->size = size;
  msg->data = new(std::nothrow) char[size];

  return (msg->data == NULL) ? -1 : 0;
}


int msgq_msg_init_data(msgq_msg_t * msg, char * data, size_t size) {
  int r = msgq_msg_init_size(msg, size);

  if (r == 0)
    memcpy(msg->data, data, size);

  return r;
}

int msgq_msg_close(msgq_msg_t * msg){
  if (msg->size > 0)
    delete[] msg->data;

  msg->size = 0;

  return 0;
}

void msgq_reset_reader(msgq_queue_t * q){
  int id = q->reader_id;
  q->read_valids[id]->store(true);
  q->read_pointers[id]->store(*q->write_pointer);
}

void msgq_wait_for_subscriber(msgq_queue_t *q){
  while (*q->num_readers == 0){
    // wait for subscriber
  }

  return;
}

int msgq_new_queue(msgq_queue_t * q, const char * path, size_t size){
  assert(size < 0xFFFFFFFF); // Buffer must be smaller than 2^32 bytes

#ifdef __APPLE__
  std::string base_path = "/tmp/msgq_";
#else
  std::string base_path = "/dev/shm/msgq_";
#endif
  const char* prefix = std::getenv("OPENPILOT_PREFIX");
  if (prefix) {
    base_path += std::string(prefix) + "/";
  }
  std::string full_path = base_path + path;

  auto fd = open(full_path.c_str(), O_RDWR | O_CREAT, 0660);
  if (fd < 0) {
    std::cout << "Warning, could not open: " << full_path << std::endl;
    return -1;
  }

  int rc = ftruncate(fd, size + sizeof(msgq_header_t));
  if (rc < 0){
    close(fd);
    return -1;
  }

  int mmap_flags = MAP_SHARED;
#ifdef MAP_POPULATE
  if (std::getenv("MSGQ_PREALLOC")) {
    mmap_flags |= MAP_POPULATE;
  }
#endif

  char * mem = (char*)mmap(NULL, size + sizeof(msgq_header_t), PROT_READ | PROT_WRITE, mmap_flags, fd, 0);
  close(fd);

  if (mem == MAP_FAILED){
    return -1;
  }

  q->mmap_p = mem;

  msgq_header_t *header = (msgq_header_t *)mem;

  // Setup pointers to header segment
  q->num_readers = reinterpret_cast<std::atomic<uint64_t>*>(&header->num_readers);
  q->write_pointer = reinterpret_cast<std::atomic<uint64_t>*>(&header->write_pointer);
  q->write_uid = reinterpret_cast<std::atomic<uint64_t>*>(&header->write_uid);

  for (size_t i = 0; i < NUM_READERS; i++){
    q->read_pointers[i] = reinterpret_cast<std::atomic<uint64_t>*>(&header->read_pointers[i]);
    q->read_valids[i] = reinterpret_cast<std::atomic<uint64_t>*>(&header->read_valids[i]);
    q->read_uids[i] = reinterpret_cast<std::atomic<uint64_t>*>(&header->read_uids[i]);
  }

  q->data = mem + sizeof(msgq_header_t);
  q->size = size;
  q->reader_id = -1;

  q->endpoint = path;
  q->read_conflate = false;

  return 0;
}

void msgq_close_queue(msgq_queue_t *q){
  if (q->mmap_p != NULL){
    msgq_remove_subscriber(q);
    munmap(q->mmap_p, q->size + sizeof(msgq_header_t));
    q->mmap_p = nullptr;
  }
  close_wake_socket(q);
}


void msgq_init_publisher(msgq_queue_t * q) {
  //std::cout << "Starting publisher" << std::endl;
  uint64_t uid = msgq_get_uid();

  *q->write_uid = uid;
  *q->num_readers = 0;

  for (size_t i = 0; i < NUM_READERS; i++){
    *q->read_valids[i] = false;
    wake_if_waiting(q->read_uids[i], 0);
  }

  q->write_uid_local = uid;
}

// claim slot i (its uid CAS already succeeded) for the calling thread
static void msgq_claim_slot(msgq_queue_t * q, size_t i, uint64_t uid) {
  q->reader_id = i;
  q->read_uid_local = uid;
  *q->read_valids[i] = false;
  *q->read_pointers[i] = 0;
}

int msgq_init_subscriber(msgq_queue_t * q) {
  assert(q != NULL);
  assert(q->num_readers != NULL);

  close_wake_socket(q);
  uint64_t uid = msgq_get_uid();

  // Get reader id
  while (true){
    uint64_t cur_num_readers = *q->num_readers;
    uint64_t new_num_readers = cur_num_readers + 1;

    // Table full: reuse a released or dead slot. num_readers is an append-only
    // high-water mark, so only slots below it are serviced by the publisher's
    // notify/invalidate loops — never claim at or above it.
    if (new_num_readers > NUM_READERS){
      bool reclaimed = false;

      // a slot zeroed by msgq_remove_subscriber (clean close)
      for (size_t i = 0; i < cur_num_readers && !reclaimed; i++){
        uint64_t expected = 0;
        if (*q->read_uids[i] == 0 &&
            std::atomic_compare_exchange_strong(q->read_uids[i], &expected, uid)){
          msgq_claim_slot(q, i, uid);
          reclaimed = true;
        }
      }

      for (size_t i = 0; i < cur_num_readers && !reclaimed; i++){
        std::atomic<uint64_t> *slot = q->read_uids[i];
        uint64_t slot_uid = *slot;
        if (slot_uid == 0 || wake_socket_alive(slot_uid))
          continue;
        if (std::atomic_compare_exchange_strong(slot, &slot_uid, uid)){
          msgq_claim_slot(q, i, uid);
          reclaimed = true;
        }
      }
      if (reclaimed)
        break;

      // NUM_READERS live readers: fail this registration. Evicting live readers
      // (the old fallback) storms every healthy subscriber of the service.
      static std::atomic<int64_t> last_full_log_us(0);
      int64_t now_us = std::chrono::duration_cast<std::chrono::microseconds>(
          std::chrono::steady_clock::now().time_since_epoch()).count();
      int64_t last_us = last_full_log_us.load(std::memory_order_relaxed);
      if (now_us - last_us > 1000000 &&
          last_full_log_us.compare_exchange_strong(last_us, now_us)) {
        std::cout << "msgq warning: subscriber table full for " << q->endpoint
                  << " (" << NUM_READERS << " live readers), registration refused" << std::endl;
        // stdout only lives in tmux scrollback and dies with a reboot; also append
        // to the persistent issue-debug file so overflow is diagnosable post-crash
        FILE *f = fopen("/data/community/iqpilot_issue_debug.txt", "a");
        if (f != NULL) {
          fprintf(f, "[msgq] subscriber table full for %s (%d live readers), registration refused\n",
                  q->endpoint.c_str(), NUM_READERS);
          fclose(f);
        }
      }
      errno = ENOBUFS;
      return -1;
    }

    // Use atomic compare and swap to handle race condition
    // where two subscribers start at the same time
    if (std::atomic_compare_exchange_strong(q->num_readers,
                                            &cur_num_readers,
                                            new_num_readers)){
      q->reader_id = cur_num_readers;
      q->read_uid_local = uid;

      // We start with read_valid = false,
      // on the first read the read pointer will be synchronized with the write pointer
      *q->read_valids[cur_num_readers] = false;
      *q->read_pointers[cur_num_readers] = 0;
      *q->read_uids[cur_num_readers] = uid;
      break;
    }
  }

  msgq_reset_reader(q);
  bind_wake_socket(q);
  return 0;
}

void msgq_remove_subscriber(msgq_queue_t * q) {
  if (q->reader_id < 0 || q->num_readers == NULL)
    return;
  // release only if the slot is still ours — a publisher restart or a reclaim
  // may have handed it to another reader
  std::atomic<uint64_t> *slot = q->read_uids[q->reader_id];
  uint64_t expected = q->read_uid_local;
  while (!std::atomic_compare_exchange_weak(slot, &expected, (uint64_t)0)){
    if ((expected & ~MSGQ_READER_WAITING) != q->read_uid_local)
      break;
  }
  if ((expected & ~MSGQ_READER_WAITING) == q->read_uid_local){
    *q->read_valids[q->reader_id] = false;
  }
  q->reader_id = -1;
}

int msgq_msg_send(msgq_msg_t * msg, msgq_queue_t *q){
  // Die if we are no longer the active publisher
  if (q->write_uid_local != *q->write_uid){
    std::cout << "Killing old publisher: " << q->endpoint << std::endl;
    errno = EADDRINUSE;
    return -1;
  }

  uint64_t total_msg_size = ALIGN(msg->size + sizeof(int64_t));

  // We need to fit at least three messages in the queue,
  // then we can always safely access the last message
  assert(3 * total_msg_size <= q->size);

  uint64_t num_readers = *q->num_readers;

  uint32_t write_cycles, write_pointer;
  UNPACK64(write_cycles, write_pointer, *q->write_pointer);

  char *p = q->data + write_pointer; // add base offset

  // Check remaining space
  // Always leave space for a wraparound tag for the next message, including alignment
  int64_t remaining_space = q->size - write_pointer - total_msg_size - sizeof(int64_t);
  if (remaining_space <= 0){
    // Write -1 size tag indicating wraparound
    *(int64_t*)p = -1;

    // Invalidate all readers that are beyond the write pointer
    // TODO: should we handle the case where a new reader shows up while this is running?
    for (uint64_t i = 0; i < num_readers; i++){
      uint64_t read_pointer = *q->read_pointers[i];
      uint64_t read_cycles = read_pointer >> 32;
      read_pointer &= 0xFFFFFFFF;

      if ((read_pointer > write_pointer) && (read_cycles != write_cycles)) {
        *q->read_valids[i] = false;
      }
    }

    // Update global and local copies of write pointer and write_cycles
    write_pointer = 0;
    write_cycles = write_cycles + 1;
    PACK64(*q->write_pointer, write_cycles, write_pointer);

    // Set actual pointer to the beginning of the data segment
    p = q->data;
  }

  // Invalidate readers that are in the area that will be written
  uint64_t start = write_pointer;
  uint64_t end = ALIGN(start + sizeof(int64_t) + msg->size);

  for (uint64_t i = 0; i < num_readers; i++){
    uint32_t read_cycles, read_pointer;
    UNPACK64(read_cycles, read_pointer, *q->read_pointers[i]);

    if ((read_pointer >= start) && (read_pointer < end) && (read_cycles != write_cycles)) {
      *q->read_valids[i] = false;
    }
  }


  // Write size tag
  std::atomic<int64_t> *size_p = reinterpret_cast<std::atomic<int64_t>*>(p);
  *size_p = msg->size;

  // Copy data
  memcpy(p + sizeof(int64_t), msg->data, msg->size);
  __sync_synchronize();

  // Update write pointer
  uint32_t new_ptr = ALIGN(write_pointer + msg->size + sizeof(int64_t));
  PACK64(*q->write_pointer, write_cycles, new_ptr);

  // Reload so a reader that subscribed and started polling during this send isn't missed
  num_readers = std::min<uint64_t>(NUM_READERS, *q->num_readers);
  for (uint64_t i = 0; i < num_readers; i++){
    if (!(*q->read_uids[i] & MSGQ_READER_WAITING))
      continue;
    uint64_t reader_uid = q->read_uids[i]->fetch_and(~MSGQ_READER_WAITING);
    if (reader_uid & MSGQ_READER_WAITING){
      wake_reader(reader_uid & ~MSGQ_READER_WAITING);
    }
  }

  return msg->size;
}


int msgq_msg_ready(msgq_queue_t * q){
 start:
  int id = q->reader_id;
  assert(id >= 0); // Make sure subscriber is initialized

  if (q->read_uid_local != (*q->read_uids[id] & ~MSGQ_READER_WAITING)){
    // publisher restart (or slot takeover) invalidated us; reconnect. If the
    // table is momentarily full, report not-ready and retry on the next call.
    if (msgq_init_subscriber(q) != 0){
      return 0;
    }
    goto start;
  }

  // Check valid
  if (!*q->read_valids[id]){
    msgq_reset_reader(q);
    goto start;
  }

  uint32_t read_cycles, read_pointer;
  UNPACK64(read_cycles, read_pointer, *q->read_pointers[id]);
  UNUSED(read_cycles);

  uint32_t write_cycles, write_pointer;
  UNPACK64(write_cycles, write_pointer, *q->write_pointer);
  UNUSED(write_cycles);

  // Check if new message is available
  return (read_pointer != write_pointer);
}

int msgq_msg_recv(msgq_msg_t * msg, msgq_queue_t * q){
 start:
  int id = q->reader_id;
  assert(id >= 0); // Make sure subscriber is initialized

  if (q->read_uid_local != (*q->read_uids[id] & ~MSGQ_READER_WAITING)){
    // publisher restart (or slot takeover) invalidated us; reconnect. If the
    // table is momentarily full, report no-message and retry on the next call.
    if (msgq_init_subscriber(q) != 0){
      msg->size = 0;
      return 0;
    }
    goto start;
  }

  // Check valid
  if (!*q->read_valids[id]){
    msgq_reset_reader(q);
    goto start;
  }

  uint32_t read_cycles, read_pointer;
  UNPACK64(read_cycles, read_pointer, *q->read_pointers[id]);

  uint32_t write_cycles, write_pointer;
  UNPACK64(write_cycles, write_pointer, *q->write_pointer);
  UNUSED(write_cycles);

  char * p = q->data + read_pointer;

  // Check if new message is available
  if (read_pointer == write_pointer) {
    msg->size = 0;
    return 0;
  }

  // Read potential message size
  std::atomic<int64_t> *size_p = reinterpret_cast<std::atomic<int64_t>*>(p);
  std::int64_t size = *size_p;

  // Check if the size that was read is valid
  if (!*q->read_valids[id]){
    msgq_reset_reader(q);
    goto start;
  }

  // If size is -1 the buffer was full, and we need to wrap around
  if (size == -1){
    read_cycles++;
    PACK64(*q->read_pointers[id], read_cycles, 0);
    goto start;
  }

  // crashing is better than passing garbage data to the consumer
  // the size will have weird value if it was overwritten by data accidentally
  assert((uint64_t)size < q->size);
  assert(size > 0);

  uint32_t new_read_pointer = ALIGN(read_pointer + sizeof(std::int64_t) + size);

  // If conflate is true, check if this is the latest message, else start over
  if (q->read_conflate){
    if (new_read_pointer != write_pointer){
      // Update read pointer
      PACK64(*q->read_pointers[id], read_cycles, new_read_pointer);
      goto start;
    }
  }

  // Copy message
  if (msgq_msg_init_size(msg, size) < 0)
    return -1;

  __sync_synchronize();
  memcpy(msg->data, p + sizeof(int64_t), size);
  __sync_synchronize();

  // Update read pointer
  PACK64(*q->read_pointers[id], read_cycles, new_read_pointer);

  // Check if the actual data that was copied is valid
  if (!*q->read_valids[id]){
    msgq_msg_close(msg);
    msgq_reset_reader(q);
    goto start;
  }


  return msg->size;
}



#ifdef __linux__
static bool epoll_track(msgq_queue_t *q) {
  PollSet &ps = t_pollset;
  if (ps.epfd < 0) {
    register_atfork_once();
    ps.epfd = epoll_create1(EPOLL_CLOEXEC);
    if (ps.epfd < 0) return false;
  }

  auto entry = std::make_pair(static_cast<const msgq_queue_t*>(q), q->read_uid_local);
  auto it = ps.regs.find(q->wake_fd);
  if (it != ps.regs.end() && it->second == entry) return true;

  epoll_event ev = {};
  ev.events = EPOLLIN | EPOLLET;
  ev.data.fd = q->wake_fd;
  if (epoll_ctl(ps.epfd, EPOLL_CTL_ADD, q->wake_fd, &ev) < 0 &&
      (errno != EEXIST || epoll_ctl(ps.epfd, EPOLL_CTL_MOD, q->wake_fd, &ev) < 0)) {
    return false;
  }
  ps.regs[q->wake_fd] = entry;
  return true;
}
#endif

int msgq_poll(msgq_pollitem_t * items, size_t nitems, int timeout){
  const int LOST_WAKEUP_CAP_MS = 100;

  auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(std::max(timeout, 0));
  static thread_local std::vector<pollfd> fds;
  static thread_local std::vector<std::atomic<uint64_t>*> armed;
  static thread_local std::vector<uint64_t> uids;
  fds.resize(nitems);
  armed.resize(nitems);
  uids.resize(nitems);

  while (true) {
    int num = 0;
    for (size_t i = 0; i < nitems; i++) {
      items[i].revents = msgq_msg_ready(items[i].q);
      num += items[i].revents;
    }
    if (num > 0) return num;

    int timeout_ms = -1;
    if (timeout >= 0) {
      auto remaining = std::chrono::ceil<std::chrono::milliseconds>(deadline - std::chrono::steady_clock::now());
      timeout_ms = std::max<int64_t>(remaining.count(), 0);
      if (timeout_ms == 0) return 0;
    }

    bool reconnected = false;
    bool can_block = true;
    for (size_t i = 0; i < nitems; i++) {
      msgq_queue_t *q = items[i].q;
      uids[i] = q->read_uid_local;

      // Arm before re-checking so a message sent in between isn't missed; the exchange fails if we were evicted
      armed[i] = q->read_uids[q->reader_id];
      uint64_t expected = uids[i];
      armed[i]->compare_exchange_strong(expected, uids[i] | MSGQ_READER_WAITING);
      num += msgq_msg_ready(q);

      reconnected |= (q->read_uid_local != uids[i]);
      can_block &= (q->wake_fd >= 0);
      fds[i] = {q->wake_fd, POLLIN, 0};
    }

    if (num == 0 && !reconnected) {
      int block_ms = timeout_ms < 0 ? LOST_WAKEUP_CAP_MS : std::min(timeout_ms, LOST_WAKEUP_CAP_MS);
#ifdef __linux__
      bool tracked = can_block;
      for (size_t i = 0; i < nitems && tracked; i++) {
        tracked = epoll_track(items[i].q);
      }
      if (tracked) {
        epoll_event events[16];
        int n = epoll_wait(t_pollset.epfd, events, 16, block_ms);
        for (int e = 0; e < n; e++) {
          for (size_t i = 0; i < nitems; i++) {
            if (fds[i].fd == events[e].data.fd) {
              drain_wake_socket(fds[i].fd);
              break;
            }
          }
        }
        for (size_t i = 0; i < nitems; i++) {
          uint64_t expected = uids[i] | MSGQ_READER_WAITING;
          armed[i]->compare_exchange_strong(expected, uids[i]);
        }
        continue;
      }
#endif
      int poll_ms = can_block ? block_ms : (timeout_ms < 0 ? 10 : std::min(timeout_ms, 10));
      poll(fds.data(), fds.size(), poll_ms);
    }

    for (size_t i = 0; i < nitems; i++) {
      // Only clears our own request; the slot may belong to someone else by now
      uint64_t expected = uids[i] | MSGQ_READER_WAITING;
      armed[i]->compare_exchange_strong(expected, uids[i]);
      if (fds[i].revents & POLLIN) {
        drain_wake_socket(fds[i].fd);
      }
    }
  }
}

bool msgq_all_readers_updated(msgq_queue_t *q) {
  uint64_t num_readers = *q->num_readers;
  for (uint64_t i = 0; i < num_readers; i++) {
    if (*q->read_valids[i] && *q->write_pointer != *q->read_pointers[i]) {
      return false;
    }
  }
  return num_readers > 0;
}
