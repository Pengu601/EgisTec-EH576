/*
 * Correlation matcher for the EgisTec EH576 - interface.
 *
 * Copyright (C) 2026 Thaddeus Stepanovich
 *
 * This library is free software; you can redistribute it and/or modify it
 * under the terms of the GNU Lesser General Public License as published by the
 * Free Software Foundation; either version 2.1 of the License, or (at your
 * option) any later version.
 */

#pragma once

#include <stdint.h>

#define EM_W 70
#define EM_H 57
#define EM_N (EM_W * EM_H)

/* Precomputed per-frame features; one of these is an enrolment template. */
typedef struct
{
  double  img[EM_N];   /* enhanced + standardized   */
  uint8_t mask[EM_N];  /* coherent-ridge pixel mask */
  double  coverage;    /* coherent fraction, 0..1   */
} EmFrame;

/* Enhance, mask and standardize a raw 3990-byte frame. */
void em_frame_compute (const uint8_t *raw, EmFrame *f);

/* Masked NCC over the coherent overlap, translation-searched. -1 if the
 * two frames never overlap enough to compare. */
double em_match (const EmFrame *a, const EmFrame *b);
