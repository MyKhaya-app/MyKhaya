import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "MyKhaya — Your family's digital home",
    short_name: "MyKhaya",
    description: "Your family's digital home",
    start_url: "/home",
    display: "standalone",
    background_color: "#FAF7F1",
    theme_color: "#7D8F7A",
    icons: [
      {
        src: "/images/mykhaya-logo-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/images/mykhaya-logo.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "any",
      },
      {
        src: "/images/mykhaya-logo-maskable.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
