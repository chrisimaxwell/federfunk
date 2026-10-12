#pragma once

#include <stddef.h>
#include <stdint.h>

// The application uses a 1600x1200 landscape canvas. The two display ICs
// consume the left/right halves of a 1200x1600 native portrait canvas.
namespace panel13in3e {
constexpr uint16_t width = 1600;
constexpr uint16_t height = 1200;
constexpr uint16_t nativeWidth = height;
constexpr uint16_t nativeHeight = width;
constexpr size_t frameBytes = static_cast<size_t>(width) * height / 2;
constexpr size_t controllerRowBytes = nativeWidth / 4;

inline void packControllerRow(const uint8_t* landscape, bool slave,
                              uint16_t nativeY, uint8_t* row) {
  // Waveshare's Paint rotation=90: nativeX=1199-y, nativeY=x.
  // Rotate only the addressing; preserve every color nibble exactly.
  const uint16_t firstNativeX = slave ? nativeWidth / 2 : 0;
  const size_t columnByte = nativeY / 2;
  const uint8_t shift = (nativeY & 1) ? 0 : 4;
  for (size_t index = 0; index < controllerRowBytes; ++index) {
    const uint16_t firstY = nativeWidth - 1 - (firstNativeX + 2 * index);
    const size_t firstOffset = static_cast<size_t>(firstY) * (width / 2) +
                               columnByte;
    const uint8_t first = (landscape[firstOffset] >> shift) & 0x0F;
    const uint8_t second =
        (landscape[firstOffset - width / 2] >> shift) & 0x0F;
    row[index] = (first << 4) | second;
  }
}
}  // namespace panel13in3e
