#ifndef _UAPI_LINUX_ION_H
#define _UAPI_LINUX_ION_H

#include <stddef.h>
#include <linux/ioctl.h>

typedef int ion_user_handle_t;

#define ION_FLAG_CACHED 1

struct ion_allocation_data {
  size_t len;
  size_t align;
  unsigned int heap_id_mask;
  unsigned int flags;
  ion_user_handle_t handle;
};

struct ion_fd_data {
  ion_user_handle_t handle;
  int fd;
};

struct ion_handle_data {
  ion_user_handle_t handle;
};

struct ion_custom_data {
  unsigned int cmd;
  unsigned long arg;
};

#define ION_IOC_MAGIC 'I'
#define ION_IOC_ALLOC _IOWR(ION_IOC_MAGIC, 0, struct ion_allocation_data)
#define ION_IOC_FREE _IOWR(ION_IOC_MAGIC, 1, struct ion_handle_data)
#define ION_IOC_SHARE _IOWR(ION_IOC_MAGIC, 4, struct ion_fd_data)
#define ION_IOC_IMPORT _IOWR(ION_IOC_MAGIC, 5, struct ion_fd_data)
#define ION_IOC_CUSTOM _IOWR(ION_IOC_MAGIC, 6, struct ion_custom_data)

#endif
