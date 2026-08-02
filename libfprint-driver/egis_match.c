/*
 * Correlation matcher for the EgisTec EH576.
 *
 * Copyright (C) 2026 Thaddeus Stepanovich
 *
 * This library is free software; you can redistribute it and/or modify it
 * under the terms of the GNU Lesser General Public License as published by the
 * Free Software Foundation; either version 2.1 of the License, or (at your
 * option) any later version.
 *
 * This library is distributed in the hope that it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 * FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License
 * for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with this library; if not, write to the Free Software Foundation,
 * Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
 */

/* C port of the
 * proven Python recipe (corr_match.py / minutiae.py):
 *
 *   enhance   = box1 then box4 high-pass (+128), edge-replicated windows
 *   mask      = per-16px-block structure-tensor coherence >= 0.20,
 *               3x3 majority vote (wraparound, matching np.roll)
 *   score     = NCC over the coherent-overlap region, +/-6 px translation
 *               search, >= 800 px overlap required
 *   coverage  = coherent fraction of the frame (capture quality gate)
 *
 * Standalone build (offline eval against dataset/):
 *   cc -O2 -DEGIS_MATCH_MAIN egis_match.c -o egis_match -lm
 */
#include <math.h>
#include <stdint.h>
#include <string.h>

#include "egis_match.h"

#define EM_BLOCK 16
#define EM_BH (EM_H / EM_BLOCK) /* 3 */
#define EM_BW (EM_W / EM_BLOCK) /* 4 */
#define EM_COH_TH 0.20
#define EM_SRCH 6
#define EM_MIN_OVERLAP 800

/* Box mean with edge replication (scipy uniform_filter mode='nearest'):
 * window indices clamp to the frame, denominator is the full window area. */
static void
em_box_mean (const double *src, double *dst, int radius)
{
  int size = 2 * radius + 1;
  double denom = (double) size * size;

  for (int y = 0; y < EM_H; y++)
    for (int x = 0; x < EM_W; x++)
      {
        double sum = 0;
        for (int dy = -radius; dy <= radius; dy++)
          for (int dx = -radius; dx <= radius; dx++)
            {
              int yy = y + dy, xx = x + dx;
              yy = yy < 0 ? 0 : (yy >= EM_H ? EM_H - 1 : yy);
              xx = xx < 0 ? 0 : (xx >= EM_W ? EM_W - 1 : xx);
              sum += src[yy * EM_W + xx];
            }
        dst[y * EM_W + x] = sum / denom;
      }
}

/* High-pass enhancement: light box mean minus heavy box mean of it, +128. */
static void
em_enhance (const uint8_t *raw, double *out)
{
  double a[EM_N], b[EM_N];

  for (int i = 0; i < EM_N; i++)
    a[i] = raw[i];
  em_box_mean (a, b, 1);        /* light smooth   */
  em_box_mean (b, a, 4);        /* background     */
  for (int i = 0; i < EM_N; i++)
    {
      double v = b[i] - a[i] + 128.0;
      out[i] = v < 0 ? 0 : (v > 255 ? 255 : v);
    }
}

/* Coherence mask from the enhanced image; also returns coverage. */
static double
em_coherence_mask (const double *enh, uint8_t *mask)
{
  double gx[EM_N] = { 0 }, gy[EM_N] = { 0 };
  double coh[EM_BH][EM_BW];
  uint8_t strong[EM_BH][EM_BW];

  for (int y = 1; y < EM_H - 1; y++)
    for (int x = 1; x < EM_W - 1; x++)
      {
        const double *r0 = enh + (y - 1) * EM_W;
        const double *r1 = enh + y * EM_W;
        const double *r2 = enh + (y + 1) * EM_W;
        gx[y * EM_W + x] = (r1[x + 1] - r1[x - 1]) * 2
                           + r0[x + 1] - r0[x - 1]
                           + r2[x + 1] - r2[x - 1];
        gy[y * EM_W + x] = (r2[x] - r0[x]) * 2
                           + r2[x - 1] - r0[x - 1]
                           + r2[x + 1] - r0[x + 1];
      }

  for (int by = 0; by < EM_BH; by++)
    for (int bx = 0; bx < EM_BW; bx++)
      {
        double gxx = 0, gyy = 0, gxy = 0;
        for (int y = by * EM_BLOCK; y < (by + 1) * EM_BLOCK; y++)
          for (int x = bx * EM_BLOCK; x < (bx + 1) * EM_BLOCK; x++)
            {
              double vx = gx[y * EM_W + x], vy = gy[y * EM_W + x];
              gxx += vx * vx;
              gyy += vy * vy;
              gxy += vx * vy;
            }
        double tr = gxx + gyy;
        coh[by][bx] = tr > 0 ? hypot (gxx - gyy, 2 * gxy) / tr : 0.0;
        strong[by][bx] = coh[by][bx] >= EM_COH_TH;
      }

  /* 3x3 majority vote with wraparound (isolated strong blocks die) */
  memset (mask, 0, EM_N);
  int kept_px = 0;
  for (int by = 0; by < EM_BH; by++)
    for (int bx = 0; bx < EM_BW; bx++)
      {
        int vote = 0;
        for (int dy = -1; dy <= 1; dy++)
          for (int dx = -1; dx <= 1; dx++)
            vote += strong[(by + dy + EM_BH) % EM_BH][(bx + dx + EM_BW) % EM_BW];
        if (strong[by][bx] && vote > 4)
          {
            for (int y = by * EM_BLOCK; y < (by + 1) * EM_BLOCK; y++)
              for (int x = bx * EM_BLOCK; x < (bx + 1) * EM_BLOCK; x++)
                mask[y * EM_W + x] = 1;
            kept_px += EM_BLOCK * EM_BLOCK;
          }
      }
  return (double) kept_px / EM_N;
}

/* Standardize to zero mean / unit variance. */
static void
em_standardize (double *img)
{
  double mean = 0, var = 0;

  for (int i = 0; i < EM_N; i++)
    mean += img[i];
  mean /= EM_N;
  for (int i = 0; i < EM_N; i++)
    {
      img[i] -= mean;
      var += img[i] * img[i];
    }
  double sd = sqrt (var / EM_N) + 1e-6;
  for (int i = 0; i < EM_N; i++)
    img[i] /= sd;
}

void
em_frame_compute (const uint8_t *raw, EmFrame *f)
{
  em_enhance (raw, f->img);
  f->coverage = em_coherence_mask (f->img, f->mask);
  em_standardize (f->img);
}

/* Masked NCC with translation search; -1 if never enough overlap. */
double
em_match (const EmFrame *a, const EmFrame *b)
{
  double best = -1.0;

  for (int dy = -EM_SRCH; dy <= EM_SRCH; dy++)
    for (int dx = -EM_SRCH; dx <= EM_SRCH; dx++)
      {
        int ay0 = dy > 0 ? dy : 0, ay1 = EM_H + (dy < 0 ? dy : 0);
        int ax0 = dx > 0 ? dx : 0, ax1 = EM_W + (dx < 0 ? dx : 0);
        double sa = 0, sb = 0;
        int n = 0;
        /* first pass: masked means */
        for (int y = ay0; y < ay1; y++)
          for (int x = ax0; x < ax1; x++)
            {
              int ia = y * EM_W + x;
              int ib = (y - dy) * EM_W + (x - dx);
              if (a->mask[ia] && b->mask[ib])
                {
                  sa += a->img[ia];
                  sb += b->img[ib];
                  n++;
                }
            }
        if (n < EM_MIN_OVERLAP)
          continue;
        double ma = sa / n, mb = sb / n;
        double num = 0, da = 0, db = 0;
        for (int y = ay0; y < ay1; y++)
          for (int x = ax0; x < ax1; x++)
            {
              int ia = y * EM_W + x;
              int ib = (y - dy) * EM_W + (x - dx);
              if (a->mask[ia] && b->mask[ib])
                {
                  double va = a->img[ia] - ma;
                  double vb = b->img[ib] - mb;
                  num += va * vb;
                  da += va * va;
                  db += vb * vb;
                }
            }
        double score = num / (sqrt (da * db) + 1e-6);
        if (score > best)
          best = score;
      }
  return best;
}

#ifdef EGIS_MATCH_MAIN
#include <stdio.h>
#include <stdlib.h>

#define FINGERS 5
#define PRESSES 8

static int
load_raw (const char *path, uint8_t *buf)
{
  FILE *f = fopen (path, "rb");

  if (!f)
    return -1;
  size_t n = fread (buf, 1, EM_N, f);
  fclose (f);
  return n == EM_N ? 0 : -1;
}

int
main (int argc, char **argv)
{
  if (argc == 3) /* match two raw frames */
    {
      uint8_t ra[EM_N], rb[EM_N];
      static EmFrame fa, fb;
      if (load_raw (argv[1], ra) || load_raw (argv[2], rb))
        {
          fprintf (stderr, "load failed\n");
          return 1;
        }
      em_frame_compute (ra, &fa);
      em_frame_compute (rb, &fb);
      printf ("coverage %.2f %.2f  score %.4f\n",
              fa.coverage, fb.coverage, em_match (&fa, &fb));
      return 0;
    }

  /* eval mode: dataset/f1..f5 x 8 presses */
  const char *dir = argc > 1 ? argv[1] : "dataset";
  static EmFrame fr[FINGERS][PRESSES];
  for (int f = 0; f < FINGERS; f++)
    for (int p = 0; p < PRESSES; p++)
      {
        char path[256];
        uint8_t raw[EM_N];
        snprintf (path, sizeof (path), "%s/f%d_%02d.bin", dir, f + 1, p);
        if (load_raw (path, raw))
          {
            fprintf (stderr, "cannot load %s\n", path);
            return 1;
          }
        em_frame_compute (raw, &fr[f][p]);
      }

  /* pairwise: genuine within finger, impostor across */
  double gen[FINGERS * PRESSES * PRESSES], imp[FINGERS * FINGERS * PRESSES * PRESSES];
  int ng = 0, ni = 0;
  for (int f = 0; f < FINGERS; f++)
    for (int i = 0; i < PRESSES; i++)
      for (int j = i + 1; j < PRESSES; j++)
        gen[ng++] = em_match (&fr[f][i], &fr[f][j]);
  for (int fa_ = 0; fa_ < FINGERS; fa_++)
    for (int fb_ = fa_ + 1; fb_ < FINGERS; fb_++)
      for (int i = 0; i < PRESSES; i++)
        for (int j = 0; j < PRESSES; j++)
          imp[ni++] = em_match (&fr[fa_][i], &fr[fb_][j]);

  double gm = 0, im = 0;
  for (int i = 0; i < ng; i++) gm += gen[i];
  for (int i = 0; i < ni; i++) im += imp[i];
  gm /= ng; im /= ni;
  double gv = 0, iv = 0;
  for (int i = 0; i < ng; i++) gv += (gen[i] - gm) * (gen[i] - gm);
  for (int i = 0; i < ni; i++) iv += (imp[i] - im) * (imp[i] - im);
  double dprime = (gm - im) / ((sqrt (gv / ng) + sqrt (iv / ni)) / 2 + 1e-9);
  printf ("pairwise: genuine mean %.3f  impostor mean %.3f  d-prime %.2f\n",
          gm, im, dprime);

  double best_th = 0, best_err = 2;
  for (double th = 0.05; th < 0.95; th += 0.01)
    {
      int far = 0, frr = 0;
      for (int i = 0; i < ni; i++) far += imp[i] >= th;
      for (int i = 0; i < ng; i++) frr += gen[i] < th;
      double e = (double) far / ni + (double) frr / ng;
      if (e < best_err) { best_err = e; best_th = th; }
    }
  {
    int far = 0, frr = 0;
    for (int i = 0; i < ni; i++) far += imp[i] >= best_th;
    for (int i = 0; i < ng; i++) frr += gen[i] < best_th;
    printf ("pairwise best op: th %.2f  FAR %.1f%%  FRR %.1f%%\n",
            best_th, 100.0 * far / ni, 100.0 * frr / ng);
  }

  /* multi-template: enroll first 5 presses, probe last 3, score best-of-N */
  int enr = 5;
  double mg[FINGERS * PRESSES], mi[FINGERS * FINGERS * PRESSES];
  int nmg = 0, nmi = 0;
  for (int f = 0; f < FINGERS; f++)
    for (int p = enr; p < PRESSES; p++)
      {
        double best = -1;
        for (int e = 0; e < enr; e++)
          {
            double s = em_match (&fr[f][p], &fr[f][e]);
            if (s > best) best = s;
          }
        mg[nmg++] = best;
      }
  for (int f = 0; f < FINGERS; f++)
    for (int g = 0; g < FINGERS; g++)
      {
        if (g == f) continue;
        for (int p = enr; p < PRESSES; p++)
          {
            double best = -1;
            for (int e = 0; e < enr; e++)
              {
                double s = em_match (&fr[g][p], &fr[f][e]);
                if (s > best) best = s;
              }
            mi[nmi++] = best;
          }
      }
  best_th = 0; best_err = 2;
  for (double th = 0.05; th < 0.95; th += 0.01)
    {
      int far = 0, frr = 0;
      for (int i = 0; i < nmi; i++) far += mi[i] >= th;
      for (int i = 0; i < nmg; i++) frr += mg[i] < th;
      double e = (double) far / nmi + (double) frr / nmg;
      if (e < best_err) { best_err = e; best_th = th; }
    }
  {
    int far = 0, frr = 0;
    for (int i = 0; i < nmi; i++) far += mi[i] >= best_th;
    for (int i = 0; i < nmg; i++) frr += mg[i] < best_th;
    printf ("multi-template(5): th %.2f  FAR %.1f%%  FRR %.1f%%  (n_gen %d n_imp %d)\n",
            best_th, 100.0 * far / nmi, 100.0 * frr / nmg, nmg, nmi);
  }
  return 0;
}
#endif
