import type { Metadata } from "next";
import Welcome from "@/components/marketing/site/welcome";

export const metadata: Metadata = {
  title: { absolute: "MyKhaya Home" },
  description:
    "MyKhaya is your family's digital home: shared calendars, meal plans, nudges and lists in one calm place. Free to start.",
};

/** mykhaya.app — the public marketing homepage (and the native shell's
 *  startup route; see Welcome). */
export default function HomePage() {
  return <Welcome />;
}
