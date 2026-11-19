#ifndef _UAPI_MSM_ION_H
#define _UAPI_MSM_ION_H

#include <linux/ion.h>

#define ION_SYSTEM_HEAP_ID 25
#define ION_IOMMU_HEAP_ID ION_SYSTEM_HEAP_ID

struct ion_flush_data {
  ion_user_handle_t handle;
  int fd;
  void *vaddr;
  unsigned int offset;
  unsigned int length;
};

#define ION_IOC_MSM_MAGIC 'M'
#define ION_IOC_CLEAN_CACHES _IOWR(ION_IOC_MSM_MAGIC, 0, struct ion_flush_data)
#define ION_IOC_INV_CACHES _IOWR(ION_IOC_MSM_MAGIC, 1, struct ion_flush_data)
#define ION_IOC_CLEAN_INV_CACHES _IOWR(ION_IOC_MSM_MAGIC, 2, struct ion_flush_data)

#endif
