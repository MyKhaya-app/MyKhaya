import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#F2EDE3",
        }}
      >
        <svg width={104} height={108} viewBox="0 0 48 50">
          <path d="M5 20 24 4l19 16v9L24 13 5 29z" fill="#7D8F7A" />
          <rect x="8" y="29" width="12" height="10" rx="3" fill="#E07A5F" />
          <rect x="23" y="29" width="12" height="10" rx="3" fill="#FAF7F1" />
          <rect x="8" y="41" width="12" height="8" rx="3" fill="#7D8F7A" />
          <rect x="23" y="41" width="12" height="8" rx="3" fill="#E9B44C" />
        </svg>
      </div>
    ),
    size,
  );
}
