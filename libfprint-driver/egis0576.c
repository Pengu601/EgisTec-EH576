/*
 * Egis Technology Inc. EH576 (1c7a:0576) driver for libfprint
 *
 * Match-on-host press sensor, 70x57 8-bit frames. Command protocol and capture
 * flow reverse-engineered from the vendor Windows UMDF driver and the
 * community project (github.com/Pengu601/EgisTec-EH576), validated on a Lenovo
 * Yoga 7 16IRL8.
 *
 * The sensing area is too small for NBIS minutiae matching (a frame holds
 * 8-19 minutiae; bozorth3 refuses to compute below 10), which rules out the
 * FpImageDevice pipeline. The vendor's own Windows engine matches ridge
 * structure instead of minutiae, and this driver does the same on the host:
 * enrolment collects several presses as templates, verification scores the
 * probe against each with masked normalized cross-correlation over the
 * coherent-ridge overlap (see egis_match.c) and takes the best.
 *
 * This library is free software; you can redistribute it and/or modify it
 * under the terms of the GNU Lesser General Public License as published by the
 * Free Software Foundation; either version 2.1 of the License, or (at your
 * option) any later version.
 */

#define FP_COMPONENT "egis0576"

#include "egis0576.h"
#include "drivers_api.h"
#include "egis_match.c"

/* Poll and image-request packets used in the capture loop. */
static const guint8 poll_cmd[] = { 0x45, 0x47, 0x49, 0x53, 0x60, 0x00, 0x00 };
static const guint8 img_req[]  = { 0x45, 0x47, 0x49, 0x53, 0x64, 0x0f, 0x96 };

/* Register 0x12 is the sensor gain (0..15; power-on default 0). Finger
 * detection runs at the low default, but the frame used for matching is
 * captured at higher gain: ridge signal-to-noise there is ~2.4x better,
 * which the correlation matcher needs to see ridge detail rather than just
 * coarse ridge flow. */
static const guint8 gain_hi_cmd[] = { 0x45, 0x47, 0x49, 0x53, 0x61, 0x12, 0x06 };
static const guint8 gain_lo_cmd[] = { 0x45, 0x47, 0x49, 0x53, 0x61, 0x12, 0x00 };

#define EGIS0576_POLL_DELAY 50

/* Press-settle tuning: each poll cycle is ~EGIS0576_POLL_DELAY ms. */
#define EGIS0576_SETTLE_FRAMES 3      /* no-improvement frames before accept */
#define EGIS0576_PRESS_FRAMES_MAX 20  /* hard cap per press                  */

/* Matcher operating points, from the 5-finger x 8-press offline evaluation */
#define EGIS0576_ENROLL_STAGES 8      /* templates per finger                */
#define EGIS0576_MIN_COVERAGE 0.55    /* reject partial presses at capture   */
#define EGIS0576_MATCH_THRESHOLD 0.28 /* best-of-templates NCC acceptance:
                                       * on-device genuine presses score
                                       * 0.36-0.39, impostors 0.11-0.12 */

/* fpi-data print format: version tag + concatenated raw template frames */
#define EGIS0576_PRINT_VERSION 1

struct _FpDeviceEgis0576
{
  FpDevice      parent;

  FpiSsm       *task_ssm;

  int           init_num;    /* index into init_pkts during init           */
  int           arm_num;     /* index into repeat_pkts while re-arming     */
  guint8       *frame;       /* EGIS0576_IMGSIZE capture buffer            */

  /* Settle logic: a press is captured over several frames while the finger
   * lands; we keep the highest-variance frame and accept once the score
   * stops improving, so a first-contact partial print is never used. */
  guint8       *best_frame;  /* highest-variance frame seen this press     */
  double        best_var;    /* its variance (0 = no finger seen yet)      */
  int           settle_num;  /* consecutive frames with no improvement     */
  int           press_num;   /* total frames since finger first detected   */
  gboolean      waiting_off;   /* press accepted, waiting for finger lift  */
  gboolean      wait_off;      /* whether this capture should wait for lift */
  gboolean      waiting_clear; /* waiting for a clear sensor before detect:
                                * a capture must consume a FRESH press, not
                                * a finger already resting on the sensor    */

  /* Enrolment state */
  GByteArray   *enroll_data; /* accepted template frames, concatenated     */
  int           enroll_stage;
};
G_DECLARE_FINAL_TYPE (FpDeviceEgis0576, fpi_device_egis0576, FPI, DEVICE_EGIS0576, FpDevice);
G_DEFINE_TYPE (FpDeviceEgis0576, fpi_device_egis0576, FP_TYPE_DEVICE);

/*
 * Finger presence: variance of the raw frame. Baseline (no finger) is ~4 on
 * this unit; a finger pushes it well past the threshold. This is the community
 * project's proven test.
 */
static double
frame_variance (const guint8 *buf, gsize len)
{
  double sum = 0.0, sqsum = 0.0;

  for (gsize i = 0; i < len; i++)
    sum += buf[i];
  double mean = sum / len;
  for (gsize i = 0; i < len; i++)
    {
      double d = buf[i] - mean;
      sqsum += d * d;
    }
  return sqsum / len;
}

/*
 * USB helpers
 */

static void
send_pkt_cb (FpiUsbTransfer *transfer, FpDevice *dev, gpointer user_data, GError *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (transfer->ssm, error);
      return;
    }
  /* read and discard the short echo response, then advance */
  FpiUsbTransfer *rx = fpi_usb_transfer_new (dev);
  rx->ssm = transfer->ssm;
  fpi_usb_transfer_fill_bulk (rx, EGIS0576_EPIN, EGIS0576_CMDRESP);
  fpi_usb_transfer_submit (rx, EGIS0576_TIMEOUT,
                           fpi_device_get_cancellable (dev),
                           fpi_ssm_usb_transfer_cb, NULL);
}

/* Send a command packet and consume its echo, then advance the SSM. */
static void
send_cmd (FpiSsm *ssm, FpDevice *dev, const guint8 *data, gsize len)
{
  FpiUsbTransfer *transfer = fpi_usb_transfer_new (dev);

  transfer->ssm = ssm;
  transfer->short_is_error = TRUE;
  fpi_usb_transfer_fill_bulk_full (transfer, EGIS0576_EPOUT,
                                   (guint8 *) data, len, NULL);
  fpi_usb_transfer_submit (transfer, EGIS0576_TIMEOUT,
                           fpi_device_get_cancellable (dev),
                           send_pkt_cb, NULL);
}

/*
 * Initialisation sub-SSM: send every init packet and consume its response. The
 * one image-flush packet (opcode 0x64) returns a full frame instead of a short
 * echo; read and discard it.
 */
enum init_states {
  I_SEND,
  I_RECV_IMG,
  I_NEXT,
  I_NUM_STATES,
};

static void
init_recv_img_cb (FpiUsbTransfer *transfer, FpDevice *dev, gpointer user_data, GError *error)
{
  if (error)
    fpi_ssm_mark_failed (transfer->ssm, error);
  else
    fpi_ssm_next_state (transfer->ssm);
}

static void
init_ssm_run (FpiSsm *ssm, FpDevice *dev)
{
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);
  const struct egis_pkt *pkt = &init_pkts[self->init_num];

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case I_SEND:
      if (EGIS0576_IS_IMG_REQ (pkt))
        {
          /* write the request, then read the frame in I_RECV_IMG */
          FpiUsbTransfer *tx = fpi_usb_transfer_new (dev);
          tx->ssm = ssm;
          tx->short_is_error = TRUE;
          fpi_usb_transfer_fill_bulk_full (tx, EGIS0576_EPOUT,
                                           (guint8 *) pkt->data, pkt->len, NULL);
          fpi_usb_transfer_submit (tx, EGIS0576_TIMEOUT,
                                   fpi_device_get_cancellable (dev),
                                   fpi_ssm_usb_transfer_cb, NULL);
        }
      else
        {
          send_cmd (ssm, dev, pkt->data, pkt->len);
        }
      break;

    case I_RECV_IMG:
      if (EGIS0576_IS_IMG_REQ (pkt))
        {
          FpiUsbTransfer *rx = fpi_usb_transfer_new (dev);
          rx->ssm = ssm;
          fpi_usb_transfer_fill_bulk (rx, EGIS0576_EPIN, EGIS0576_IMGSIZE);
          fpi_usb_transfer_submit (rx, EGIS0576_TIMEOUT,
                                   fpi_device_get_cancellable (dev),
                                   init_recv_img_cb, NULL);
        }
      else
        {
          fpi_ssm_next_state (ssm);
        }
      break;

    case I_NEXT:
      self->init_num += 1;
      if (self->init_num < (int) EGIS0576_INIT_TOTAL)
        fpi_ssm_jump_to_state (ssm, I_SEND);
      else
        fpi_ssm_mark_completed (ssm);
      break;
    }
}

static FpiSsm *
init_ssm_new (FpDevice *dev)
{
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);

  self->init_num = 0;
  return fpi_ssm_new (dev, init_ssm_run, I_NUM_STATES);
}

/*
 * Capture sub-SSM: poll until a finger settles, leave the peak-variance frame
 * in self->best_frame. If self->wait_off is set, additionally poll until the
 * finger lifts before completing (used between enrolment stages).
 */
enum capture_states {
  C_WAIT,        /* small delay between polls                    */
  C_ARM_SEND,    /* send repeat_pkts[arm_num] (re-arm)           */
  C_ARM_LOOP,    /* advance arm_num, repeat or continue          */
  C_POLL,        /* send poll command                            */
  C_IMG_REQ,     /* send image request                           */
  C_IMG_READ,    /* read the 3990-byte frame                     */
  C_CHECK,       /* variance test / settle / lift-wait           */
  C_GAIN_HI,     /* press settled: raise gain for the match frame */
  C_HQ_ARM_SEND, /* re-arm: an image request without a fresh      */
  C_HQ_ARM_LOOP, /* repeat-sequence prelude returns a blank frame */
  C_HQ_REQ,      /* request the high-gain frame                  */
  C_HQ_READ,     /* read it into best_frame                      */
  C_GAIN_LO,     /* restore default gain                         */
  C_AFTER_HQ,    /* complete, or wait for lift first             */
  C_NUM_STATES,
};

static void
img_read_cb (FpiUsbTransfer *transfer, FpDevice *dev, gpointer user_data, GError *error)
{
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);

  if (error)
    {
      fpi_ssm_mark_failed (transfer->ssm, error);
      return;
    }
  memcpy (self->frame, transfer->buffer, EGIS0576_IMGSIZE);
  fpi_ssm_next_state (transfer->ssm);
}

/* The high-gain matching frame replaces the settle-tracking best frame. */
static void
hq_read_cb (FpiUsbTransfer *transfer, FpDevice *dev, gpointer user_data, GError *error)
{
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);

  if (error)
    {
      fpi_ssm_mark_failed (transfer->ssm, error);
      return;
    }
  memcpy (self->best_frame, transfer->buffer, EGIS0576_IMGSIZE);
  fpi_ssm_next_state (transfer->ssm);
}

static void
capture_ssm_run (FpiSsm *ssm, FpDevice *dev)
{
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case C_WAIT:
      self->arm_num = 0;
      fpi_ssm_next_state_delayed (ssm, EGIS0576_POLL_DELAY);
      break;

    case C_ARM_SEND:
      send_cmd (ssm, dev, repeat_pkts[self->arm_num].data,
                repeat_pkts[self->arm_num].len);
      break;

    case C_ARM_LOOP:
      self->arm_num += 1;
      if (self->arm_num < (int) EGIS0576_REPEAT_TOTAL)
        fpi_ssm_jump_to_state (ssm, C_ARM_SEND);
      else
        fpi_ssm_next_state (ssm);
      break;

    case C_POLL:
      send_cmd (ssm, dev, poll_cmd, sizeof (poll_cmd));
      break;

    case C_IMG_REQ:
      {
        FpiUsbTransfer *tx = fpi_usb_transfer_new (dev);
        tx->ssm = ssm;
        tx->short_is_error = TRUE;
        fpi_usb_transfer_fill_bulk_full (tx, EGIS0576_EPOUT,
                                         (guint8 *) img_req, sizeof (img_req), NULL);
        fpi_usb_transfer_submit (tx, EGIS0576_TIMEOUT,
                                 fpi_device_get_cancellable (dev),
                                 fpi_ssm_usb_transfer_cb, NULL);
      }
      break;

    case C_IMG_READ:
      {
        FpiUsbTransfer *rx = fpi_usb_transfer_new (dev);
        rx->ssm = ssm;
        fpi_usb_transfer_fill_bulk (rx, EGIS0576_EPIN, EGIS0576_IMGSIZE);
        fpi_usb_transfer_submit (rx, EGIS0576_TIMEOUT,
                                 fpi_device_get_cancellable (dev),
                                 img_read_cb, NULL);
      }
      break;

    case C_CHECK:
      {
        double var = frame_variance (self->frame, EGIS0576_IMGSIZE);

        fp_dbg ("frame variance %.1f (threshold %.1f)", var, (double) EGIS0576_VAR_THRESHOLD);

        if (self->waiting_clear)
          {
            if (var < EGIS0576_VAR_THRESHOLD)
              self->waiting_clear = FALSE;
            fpi_ssm_jump_to_state (ssm, C_WAIT);
            break;
          }

        if (self->waiting_off)
          {
            if (var < EGIS0576_VAR_THRESHOLD)
              {
                fpi_device_report_finger_status (dev, FP_FINGER_STATUS_NONE);
                fpi_ssm_mark_completed (ssm);
              }
            else
              {
                fpi_ssm_jump_to_state (ssm, C_WAIT);
              }
            break;
          }

        if (var < EGIS0576_VAR_THRESHOLD)
          {
            if (self->best_var > 0)
              {
                /* finger lifted mid-settle: try the high-gain capture anyway;
                 * if the finger is really gone the frame fails the coverage
                 * gate downstream and the stage retries */
                fpi_ssm_jump_to_state (ssm, C_GAIN_HI);
              }
            else
              {
                fpi_ssm_jump_to_state (ssm, C_WAIT);
              }
            break;
          }

        if (self->best_var == 0)
          fpi_device_report_finger_status (dev, FP_FINGER_STATUS_PRESENT);

        self->press_num++;
        if (var > self->best_var)
          {
            self->best_var = var;
            self->settle_num = 0;
            memcpy (self->best_frame, self->frame, EGIS0576_IMGSIZE);
          }
        else
          {
            self->settle_num++;
          }

        if (self->settle_num >= EGIS0576_SETTLE_FRAMES ||
            self->press_num >= EGIS0576_PRESS_FRAMES_MAX)
          fpi_ssm_next_state (ssm);
        else
          fpi_ssm_jump_to_state (ssm, C_WAIT);
      }
      break;

    case C_GAIN_HI:
      self->arm_num = 0;
      send_cmd (ssm, dev, gain_hi_cmd, sizeof (gain_hi_cmd));
      break;

    case C_HQ_ARM_SEND:
      send_cmd (ssm, dev, repeat_pkts[self->arm_num].data,
                repeat_pkts[self->arm_num].len);
      break;

    case C_HQ_ARM_LOOP:
      self->arm_num += 1;
      if (self->arm_num < (int) EGIS0576_REPEAT_TOTAL)
        fpi_ssm_jump_to_state (ssm, C_HQ_ARM_SEND);
      else
        fpi_ssm_next_state (ssm);
      break;

    case C_HQ_REQ:
      {
        FpiUsbTransfer *tx = fpi_usb_transfer_new (dev);
        tx->ssm = ssm;
        tx->short_is_error = TRUE;
        fpi_usb_transfer_fill_bulk_full (tx, EGIS0576_EPOUT,
                                         (guint8 *) img_req, sizeof (img_req), NULL);
        fpi_usb_transfer_submit (tx, EGIS0576_TIMEOUT,
                                 fpi_device_get_cancellable (dev),
                                 fpi_ssm_usb_transfer_cb, NULL);
      }
      break;

    case C_HQ_READ:
      {
        FpiUsbTransfer *rx = fpi_usb_transfer_new (dev);
        rx->ssm = ssm;
        fpi_usb_transfer_fill_bulk (rx, EGIS0576_EPIN, EGIS0576_IMGSIZE);
        fpi_usb_transfer_submit (rx, EGIS0576_TIMEOUT,
                                 fpi_device_get_cancellable (dev),
                                 hq_read_cb, NULL);
      }
      break;

    case C_GAIN_LO:
      send_cmd (ssm, dev, gain_lo_cmd, sizeof (gain_lo_cmd));
      break;

    case C_AFTER_HQ:
      if (self->wait_off)
        {
          self->waiting_off = TRUE;
          fpi_ssm_jump_to_state (ssm, C_WAIT);
        }
      else
        {
          fpi_device_report_finger_status (dev, FP_FINGER_STATUS_NONE);
          fpi_ssm_mark_completed (ssm);
        }
      break;
    }
}

static FpiSsm *
capture_ssm_new (FpDevice *dev, gboolean wait_off)
{
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);

  self->best_var = 0;
  self->settle_num = 0;
  self->press_num = 0;
  self->waiting_off = FALSE;
  self->wait_off = wait_off;
  self->waiting_clear = TRUE;
  fpi_device_report_finger_status (dev, FP_FINGER_STATUS_NEEDED);
  return fpi_ssm_new (dev, capture_ssm_run, C_NUM_STATES);
}

/*
 * Template (de)serialisation. fpi-data is "(qay)": format version plus the
 * accepted raw frames concatenated. Raw frames rather than derived features
 * so the matcher can evolve without invalidating enrolments.
 */

static void
egis0576_print_from_templates (FpPrint *print, GByteArray *raws)
{
  GVariant *data;

  fpi_print_set_type (print, FPI_PRINT_RAW);
  fpi_print_set_device_stored (print, FALSE);
  data = g_variant_new ("(q@ay)", EGIS0576_PRINT_VERSION,
                        g_variant_new_fixed_array (G_VARIANT_TYPE_BYTE,
                                                   raws->data, raws->len, 1));
  g_object_set (print, "fpi-data", data, NULL);
}

/* Returns the number of template frames, or 0 on malformed data. */
static gsize
egis0576_print_get_templates (FpPrint *print, const guint8 **out_raws)
{
  g_autoptr(GVariant) data = NULL;
  g_autoptr(GVariant) raws = NULL;
  guint16 version;
  gsize len = 0;

  g_object_get (print, "fpi-data", &data, NULL);
  if (!data || !g_variant_check_format_string (data, "(q@ay)", FALSE))
    return 0;
  g_variant_get (data, "(q@ay)", &version, &raws);
  if (version != EGIS0576_PRINT_VERSION)
    return 0;
  *out_raws = g_variant_get_fixed_array (raws, &len, 1);
  /* the fixed array data lives as long as the variant; keep it alive by
   * sinking a ref into the print so callers can use the pointer */
  g_object_set_data_full (G_OBJECT (print), "egis0576-raws",
                          g_variant_ref (raws), (GDestroyNotify) g_variant_unref);
  return len / EGIS0576_IMGSIZE;
}

/*
 * Enrolment: EGIS0576_ENROLL_STAGES accepted presses, coverage-gated.
 */
enum enroll_states {
  E_INIT,
  E_CAPTURE,
  E_PROCESS,
  E_DONE,
  E_NUM_STATES,
};

static void
enroll_ssm_run (FpiSsm *ssm, FpDevice *dev)
{
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case E_INIT:
      fpi_ssm_start_subsm (ssm, init_ssm_new (dev));
      break;

    case E_CAPTURE:
      fpi_ssm_start_subsm (ssm, capture_ssm_new (dev, TRUE));
      break;

    case E_PROCESS:
      {
        static EmFrame probe;
        em_frame_compute (self->best_frame, &probe);

        if (probe.coverage < EGIS0576_MIN_COVERAGE)
          {
            fp_dbg ("enroll stage rejected: coverage %.2f", probe.coverage);
            fpi_device_enroll_progress (dev, self->enroll_stage, NULL,
                                        fpi_device_retry_new (FP_DEVICE_RETRY_CENTER_FINGER));
            fpi_ssm_jump_to_state (ssm, E_CAPTURE);
            break;
          }

        g_byte_array_append (self->enroll_data, self->best_frame, EGIS0576_IMGSIZE);
        self->enroll_stage++;
        fp_dbg ("enroll stage %d accepted (coverage %.2f)",
                self->enroll_stage, probe.coverage);
        fpi_device_enroll_progress (dev, self->enroll_stage, NULL, NULL);

        if (self->enroll_stage < EGIS0576_ENROLL_STAGES)
          fpi_ssm_jump_to_state (ssm, E_CAPTURE);
        else
          fpi_ssm_next_state (ssm);
      }
      break;

    case E_DONE:
      {
        FpPrint *print = NULL;
        fpi_device_get_enroll_data (dev, &print);
        egis0576_print_from_templates (print, self->enroll_data);
        fpi_ssm_mark_completed (ssm);
      }
      break;
    }
}

static void
enroll_ssm_done (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);
  FpPrint *print = NULL;

  self->task_ssm = NULL;
  g_clear_pointer (&self->enroll_data, g_byte_array_unref);

  if (error)
    {
      fpi_device_enroll_complete (dev, NULL, error);
      return;
    }
  fpi_device_get_enroll_data (dev, &print);
  fpi_device_enroll_complete (dev, g_object_ref (print), NULL);
}

static void
egis0576_enroll (FpDevice *dev)
{
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);

  g_assert (self->task_ssm == NULL);
  self->enroll_stage = 0;
  self->enroll_data = g_byte_array_new ();
  self->task_ssm = fpi_ssm_new (dev, enroll_ssm_run, E_NUM_STATES);
  fpi_ssm_start (self->task_ssm, enroll_ssm_done);
}

/*
 * Identification (also serves verification: libfprint runs verify through
 * identify with a one-print gallery when the verify vfunc is absent).
 */
enum identify_states {
  D_INIT,
  D_CAPTURE,
  D_MATCH,
  D_NUM_STATES,
};

static void
identify_ssm_run (FpiSsm *ssm, FpDevice *dev)
{
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case D_INIT:
      fpi_ssm_start_subsm (ssm, init_ssm_new (dev));
      break;

    case D_CAPTURE:
      fpi_ssm_start_subsm (ssm, capture_ssm_new (dev, FALSE));
      break;

    case D_MATCH:
      {
        static EmFrame probe, tmpl;
        GPtrArray *prints = NULL;
        FpPrint *best_print = NULL;
        double best_score = -1.0;

        const char *dump_dir = g_getenv ("EGIS0576_DEBUG_DUMP");
        if (dump_dir)
          {
            g_autofree char *path = g_strdup_printf ("%s/probe-%ld.bin", dump_dir,
                                                     (long) getpid ());
            g_file_set_contents (path, (const char *) self->best_frame,
                                 EGIS0576_IMGSIZE, NULL);
          }

        em_frame_compute (self->best_frame, &probe);
        if (probe.coverage < EGIS0576_MIN_COVERAGE)
          {
            fp_dbg ("identify probe rejected: coverage %.2f", probe.coverage);
            fpi_device_identify_report (dev, NULL, NULL,
                                        fpi_device_retry_new (FP_DEVICE_RETRY_CENTER_FINGER));
            fpi_ssm_mark_completed (ssm);
            break;
          }

        fpi_device_get_identify_data (dev, &prints);
        for (guint i = 0; prints && i < prints->len; i++)
          {
            FpPrint *print = g_ptr_array_index (prints, i);
            const guint8 *raws = NULL;
            gsize n = egis0576_print_get_templates (print, &raws);

            for (gsize t = 0; t < n; t++)
              {
                em_frame_compute (raws + t * EGIS0576_IMGSIZE, &tmpl);
                double s = em_match (&probe, &tmpl);
                fp_dbg ("template %u/%u score %.3f", (guint) t + 1, (guint) n, s);
                if (s > best_score)
                  {
                    best_score = s;
                    best_print = print;
                  }
              }
          }

        fp_dbg ("identify best score %.3f (threshold %.2f)",
                best_score, EGIS0576_MATCH_THRESHOLD);
        if (best_print && best_score >= EGIS0576_MATCH_THRESHOLD)
          fpi_device_identify_report (dev, best_print, NULL, NULL);
        else
          fpi_device_identify_report (dev, NULL, NULL, NULL);
        fpi_ssm_mark_completed (ssm);
      }
      break;
    }
}

static void
identify_ssm_done (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);

  self->task_ssm = NULL;
  fpi_device_identify_complete (dev, error);
}

static void
egis0576_identify (FpDevice *dev)
{
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);

  g_assert (self->task_ssm == NULL);
  self->task_ssm = fpi_ssm_new (dev, identify_ssm_run, D_NUM_STATES);
  fpi_ssm_start (self->task_ssm, identify_ssm_done);
}

/*
 * Open / close
 */

static void
egis0576_open (FpDevice *dev)
{
  GError *error = NULL;
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);
  GUsbDevice *usb = fpi_device_get_usb_device (dev);

  /* Select configuration 1 before claiming the interface. This mirrors what
   * pyusb's set_configuration() does: it resets the endpoint toggles/halts, and
   * without it the first bulk OUT transfer times out on this sensor. */
  if (!g_usb_device_set_configuration (usb, EGIS0576_CONF, &error))
    {
      fpi_device_open_complete (dev, error);
      return;
    }
  if (!g_usb_device_claim_interface (usb, EGIS0576_INTF, 0, &error))
    {
      fpi_device_open_complete (dev, error);
      return;
    }
  self->frame = g_malloc0 (EGIS0576_IMGSIZE);
  self->best_frame = g_malloc0 (EGIS0576_IMGSIZE);
  fpi_device_open_complete (dev, NULL);
}

static void
egis0576_close (FpDevice *dev)
{
  GError *error = NULL;
  FpDeviceEgis0576 *self = FPI_DEVICE_EGIS0576 (dev);

  g_clear_pointer (&self->frame, g_free);
  g_clear_pointer (&self->best_frame, g_free);
  g_usb_device_release_interface (fpi_device_get_usb_device (dev),
                                  EGIS0576_INTF, 0, &error);
  fpi_device_close_complete (dev, error);
}

static void
fpi_device_egis0576_init (FpDeviceEgis0576 *self)
{
}

static const FpIdEntry egis0576_id_table[] = {
  { .vid = 0x1c7a, .pid = 0x0576 },
  { .vid = 0, .pid = 0, .driver_data = 0 },
};

static void
fpi_device_egis0576_class_init (FpDeviceEgis0576Class *klass)
{
  FpDeviceClass *dev_class = FP_DEVICE_CLASS (klass);

  dev_class->id = FP_COMPONENT;
  dev_class->full_name = "Egis Technology Inc. EH576";
  dev_class->type = FP_DEVICE_TYPE_USB;
  dev_class->scan_type = FP_SCAN_TYPE_PRESS;
  dev_class->id_table = egis0576_id_table;
  dev_class->nr_enroll_stages = EGIS0576_ENROLL_STAGES;

  dev_class->open = egis0576_open;
  dev_class->close = egis0576_close;
  dev_class->enroll = egis0576_enroll;
  dev_class->identify = egis0576_identify;

  fpi_device_class_auto_initialize_features (dev_class);
}
