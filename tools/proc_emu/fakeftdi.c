/*
 * fakeftdi.c - libftdi1 for a P-ROC that is not there.
 *
 * libpinproc (PRHardware.cpp) reaches the P-ROC / P3-ROC through libftdi1:
 * find the FT245RL (0403:6001) or FT240X (0403:6015), open it, then
 * ftdi_write_data() / ftdi_read_data() whole 32-bit words.  This library
 * exports the same symbols (so it works as LD_PRELOAD, or as libftdi1.so.2
 * on LD_LIBRARY_PATH) and turns the device into a unix socket to prochw.py,
 * which plays the FPGA.  Every byte passes through untouched: the protocol
 * lives in prochw.py, once, for this and for pystub/pinproc.py alike.
 *
 * The socket is $PROC_EMU_FPGA, else /var/tmp/pad_proc/rig$PAD_SLOT/fpga.sock.
 * No daemon listening = no FTDI device, which libpinproc reports the way it
 * would with the board unplugged.
 *
 * The caller's struct ftdi_context is never written (its layout differs
 * between libftdi releases); the one device list entry is ours.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#define EXPORT __attribute__((visibility("default")))

struct ftdi_context;
struct libusb_device;
struct ftdi_device_list {
    struct ftdi_device_list *next;
    struct libusb_device *dev;
};

static int fd = -1;
static const char *last_error = "";
static char dev_token;                  /* the one "libusb_device" we hand out */

static const char *sock_path(void)
{
    static char path[108];
    const char *env = getenv("PROC_EMU_FPGA");
    const char *slot = getenv("PAD_SLOT");
    if (env && *env)
        return env;
    snprintf(path, sizeof path, "/var/tmp/pad_proc/rig%s/fpga.sock", slot && *slot ? slot : "0");
    return path;
}

static int try_connect(void)
{
    struct sockaddr_un a;
    int s = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (s < 0)
        return -1;
    memset(&a, 0, sizeof a);
    a.sun_family = AF_UNIX;
    snprintf(a.sun_path, sizeof a.sun_path, "%s", sock_path());
    if (connect(s, (struct sockaddr *)&a, sizeof a) < 0) {
        close(s);
        return -1;
    }
    return s;
}

static int device_present(int vendor, int product)
{
    int s;
    if (vendor != 0x0403 || (product != 0x6001 && product != 0x6015 && product != 0))
        return 0;
    if (fd >= 0)
        return 1;
    s = try_connect();
    if (s < 0)
        return 0;
    close(s);
    return 1;
}

/* ---- context */
EXPORT int ftdi_init(struct ftdi_context *ftdi) { (void)ftdi; return 0; }
EXPORT void ftdi_deinit(struct ftdi_context *ftdi) { (void)ftdi; }
EXPORT struct ftdi_context *ftdi_new(void) { return calloc(1, 4096); }
EXPORT void ftdi_free(struct ftdi_context *ftdi) { free(ftdi); }
EXPORT char *ftdi_get_error_string(struct ftdi_context *ftdi) { (void)ftdi; return (char *)last_error; }
EXPORT int ftdi_set_interface(struct ftdi_context *ftdi, int iface) { (void)ftdi; (void)iface; return 0; }
EXPORT void ftdi_set_usbdev(struct ftdi_context *ftdi, void *usb) { (void)ftdi; (void)usb; }

/* ---- discovery */
EXPORT int ftdi_usb_find_all(struct ftdi_context *ftdi, struct ftdi_device_list **devlist,
                             int vendor, int product)
{
    (void)ftdi;
    *devlist = NULL;
    if (!device_present(vendor, product))
        return 0;
    *devlist = calloc(1, sizeof **devlist);
    if (!*devlist)
        return -3;
    (*devlist)->dev = (struct libusb_device *)&dev_token;
    return 1;
}

EXPORT void ftdi_list_free(struct ftdi_device_list **devlist)
{
    struct ftdi_device_list *d = *devlist, *n;
    while (d) {
        n = d->next;
        free(d);
        d = n;
    }
    *devlist = NULL;
}

EXPORT void ftdi_list_free2(struct ftdi_device_list *devlist)
{
    ftdi_list_free(&devlist);
}

static int copy_str(char *dst, int len, const char *src)
{
    if (dst && len > 0) {
        strncpy(dst, src, (size_t)len - 1);
        dst[len - 1] = 0;
    }
    return 0;
}

EXPORT int ftdi_usb_get_strings(struct ftdi_context *ftdi, struct libusb_device *dev,
                                char *manufacturer, int mnf_len, char *description,
                                int desc_len, char *serial, int serial_len)
{
    (void)ftdi; (void)dev;
    copy_str(manufacturer, mnf_len, "Multimorphic, Inc.");
    copy_str(description, desc_len, "P3-ROC (PAD emulated)");
    copy_str(serial, serial_len, "PADEMU01");
    return 0;
}

EXPORT int ftdi_usb_get_strings2(struct ftdi_context *ftdi, struct libusb_device *dev,
                                 char *manufacturer, int mnf_len, char *description,
                                 int desc_len, char *serial, int serial_len)
{
    return ftdi_usb_get_strings(ftdi, dev, manufacturer, mnf_len, description, desc_len,
                                serial, serial_len);
}

/* ---- open / close */
static int open_link(void)
{
    if (fd >= 0)
        return 0;
    fd = try_connect();
    if (fd < 0) {
        last_error = "device not found";
        return -3;
    }
    return 0;
}

EXPORT int ftdi_usb_open(struct ftdi_context *ftdi, int vendor, int product)
{
    (void)ftdi;
    if (!device_present(vendor, product)) {
        last_error = "device not found";
        return -3;
    }
    return open_link();
}

EXPORT int ftdi_usb_open_desc(struct ftdi_context *ftdi, int vendor, int product,
                              const char *description, const char *serial)
{
    (void)description; (void)serial;
    return ftdi_usb_open(ftdi, vendor, product);
}

EXPORT int ftdi_usb_open_desc_index(struct ftdi_context *ftdi, int vendor, int product,
                                    const char *description, const char *serial,
                                    unsigned int index)
{
    if (index > 0) {
        last_error = "device not found";
        return -3;
    }
    return ftdi_usb_open_desc(ftdi, vendor, product, description, serial);
}

EXPORT int ftdi_usb_open_bus_addr(struct ftdi_context *ftdi, unsigned char bus, unsigned char addr)
{
    (void)ftdi; (void)bus; (void)addr;
    return open_link();
}

EXPORT int ftdi_usb_open_dev(struct ftdi_context *ftdi, struct libusb_device *dev)
{
    (void)ftdi; (void)dev;
    return open_link();
}

EXPORT int ftdi_usb_open_string(struct ftdi_context *ftdi, const char *description)
{
    (void)ftdi; (void)description;
    return open_link();
}

EXPORT int ftdi_usb_close(struct ftdi_context *ftdi)
{
    (void)ftdi;
    if (fd >= 0)
        close(fd);
    fd = -1;
    return 0;
}

/* ---- settings libpinproc and friends touch: all accepted, none matter */
EXPORT int ftdi_usb_reset(struct ftdi_context *ftdi) { (void)ftdi; return 0; }
EXPORT int ftdi_usb_purge_buffers(struct ftdi_context *ftdi) { (void)ftdi; return 0; }
EXPORT int ftdi_usb_purge_rx_buffer(struct ftdi_context *ftdi) { (void)ftdi; return 0; }
EXPORT int ftdi_usb_purge_tx_buffer(struct ftdi_context *ftdi) { (void)ftdi; return 0; }
EXPORT int ftdi_tcioflush(struct ftdi_context *ftdi) { (void)ftdi; return 0; }
EXPORT int ftdi_tciflush(struct ftdi_context *ftdi) { (void)ftdi; return 0; }
EXPORT int ftdi_tcoflush(struct ftdi_context *ftdi) { (void)ftdi; return 0; }
EXPORT int ftdi_set_baudrate(struct ftdi_context *ftdi, int baud) { (void)ftdi; (void)baud; return 0; }
EXPORT int ftdi_set_line_property(struct ftdi_context *ftdi, int bits, int sbit, int parity)
{ (void)ftdi; (void)bits; (void)sbit; (void)parity; return 0; }
EXPORT int ftdi_set_line_property2(struct ftdi_context *ftdi, int bits, int sbit, int parity, int brk)
{ (void)ftdi; (void)bits; (void)sbit; (void)parity; (void)brk; return 0; }
EXPORT int ftdi_setflowctrl(struct ftdi_context *ftdi, int flowctrl) { (void)ftdi; (void)flowctrl; return 0; }
EXPORT int ftdi_setdtr_rts(struct ftdi_context *ftdi, int dtr, int rts) { (void)ftdi; (void)dtr; (void)rts; return 0; }
EXPORT int ftdi_setdtr(struct ftdi_context *ftdi, int state) { (void)ftdi; (void)state; return 0; }
EXPORT int ftdi_setrts(struct ftdi_context *ftdi, int state) { (void)ftdi; (void)state; return 0; }
EXPORT int ftdi_set_bitmode(struct ftdi_context *ftdi, unsigned char mask, unsigned char mode)
{ (void)ftdi; (void)mask; (void)mode; return 0; }
EXPORT int ftdi_disable_bitbang(struct ftdi_context *ftdi) { (void)ftdi; return 0; }
EXPORT int ftdi_set_latency_timer(struct ftdi_context *ftdi, unsigned char latency)
{ (void)ftdi; (void)latency; return 0; }
EXPORT int ftdi_get_latency_timer(struct ftdi_context *ftdi, unsigned char *latency)
{ (void)ftdi; *latency = 2; return 0; }
EXPORT int ftdi_read_data_set_chunksize(struct ftdi_context *ftdi, unsigned int chunksize)
{ (void)ftdi; (void)chunksize; return 0; }
EXPORT int ftdi_write_data_set_chunksize(struct ftdi_context *ftdi, unsigned int chunksize)
{ (void)ftdi; (void)chunksize; return 0; }
EXPORT int ftdi_read_data_get_chunksize(struct ftdi_context *ftdi, unsigned int *chunksize)
{ (void)ftdi; *chunksize = 4096; return 0; }
EXPORT int ftdi_write_data_get_chunksize(struct ftdi_context *ftdi, unsigned int *chunksize)
{ (void)ftdi; *chunksize = 4096; return 0; }
EXPORT int ftdi_read_chipid(struct ftdi_context *ftdi, unsigned int *chipid)
{ (void)ftdi; *chipid = 0x50414445; return 0; }    /* "PADE" */
EXPORT int ftdi_poll_modem_status(struct ftdi_context *ftdi, unsigned short *status)
{ (void)ftdi; *status = 0; return 0; }

/* ---- the data path */
EXPORT int ftdi_write_data(struct ftdi_context *ftdi, const unsigned char *buf, int size)
{
    int done = 0;
    (void)ftdi;
    if (fd < 0) {
        last_error = "usb device unavailable";
        return -666;
    }
    while (done < size) {
        ssize_t n = send(fd, buf + done, (size_t)(size - done), MSG_NOSIGNAL);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            last_error = "usb bulk write failed";
            return -1;
        }
        done += (int)n;
    }
    return done;
}

EXPORT int ftdi_read_data(struct ftdi_context *ftdi, unsigned char *buf, int size)
{
    /* Like the chip with latency timer 2: whatever arrived, after at most
     * a couple of milliseconds.  libpinproc polls this in a loop. */
    struct pollfd p;
    ssize_t n;
    (void)ftdi;
    if (fd < 0) {
        last_error = "usb device unavailable";
        return -666;
    }
    if (size <= 0)
        return 0;
    p.fd = fd;
    p.events = POLLIN;
    if (poll(&p, 1, 2) <= 0)
        return 0;
    n = recv(fd, buf, (size_t)size, MSG_DONTWAIT);
    if (n < 0)
        return (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) ? 0 : -1;
    if (n == 0) {                       /* daemon gone: the board was unplugged */
        last_error = "usb bulk read failed";
        return -1;
    }
    return (int)n;
}
