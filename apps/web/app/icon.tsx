import { ImageResponse } from "next/og";

export const size = { width: 48, height: 50 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <svg width={48} height={50} viewBox="0 0 48 50">
        <path d="M5 20 24 4l19 16v9L24 13 5 29z" fill="#7D8F7A" />
        <rect x="8" y="29" width="12" height="10" rx="3" fill="#E07A5F" />
        <rect x="23" y="29" width="12" height="10" rx="3" fill="#F2EDE3" />
        <rect x="8" y="41" width="12" height="8" rx="3" fill="#7D8F7A" />
        <rect x="23" y="41" width="12" height="8" rx="3" fill="#E9B44C" />
      </svg>
    ),
    size,
  );
}
