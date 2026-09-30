/* The slice of libftdi1's <ftdi.h> that libpinproc's PRHardware.cpp compiles
 * against - enough to build the real libpinproc for the self-test without
 * libftdi1-dev (and libusb-1.0-dev) on the machine.  The symbols resolve to
 * fakeftdi.c at run time exactly as a title's own libpinproc would.
 * ftdi_context is only ever passed by address; its size here is generous. */
#ifndef PAD_FAKE_FTDI_H
#define PAD_FAKE_FTDI_H
#ifdef __cplusplus
extern "C" {
#endif

struct libusb_device;
enum ftdi_chip_type { TYPE_AM = 0, TYPE_BM = 1, TYPE_2232C = 2, TYPE_R = 3 };
struct ftdi_context {
    void *usb_ctx;
    void *usb_dev;
    int usb_read_timeout;
    int usb_write_timeout;
    enum ftdi_chip_type type;
    char reserved[4096];
};
struct ftdi_device_list {
    struct ftdi_device_list *next;
    struct libusb_device *dev;
};

int ftdi_init(struct ftdi_context *ftdi);
void ftdi_deinit(struct ftdi_context *ftdi);
char *ftdi_get_error_string(struct ftdi_context *ftdi);
int ftdi_usb_find_all(struct ftdi_context *ftdi, struct ftdi_device_list **devlist,
                      int vendor, int product);
void ftdi_list_free(struct ftdi_device_list **devlist);
int ftdi_usb_get_strings(struct ftdi_context *ftdi, struct libusb_device *dev,
                         char *manufacturer, int mnf_len, char *description, int desc_len,
                         char *serial, int serial_len);
int ftdi_usb_open(struct ftdi_context *ftdi, int vendor, int product);
int ftdi_usb_close(struct ftdi_context *ftdi);
int ftdi_read_chipid(struct ftdi_context *ftdi, unsigned int *chipid);
int ftdi_read_data_set_chunksize(struct ftdi_context *ftdi, unsigned int chunksize);
int ftdi_set_latency_timer(struct ftdi_context *ftdi, unsigned char latency);
int ftdi_read_data(struct ftdi_context *ftdi, unsigned char *buf, int size);
int ftdi_write_data(struct ftdi_context *ftdi, const unsigned char *buf, int size);

#ifdef __cplusplus
}
#endif
#endif
