import { NextResponse } from "next/server";
import manifestDefinition from "../manifest-definition";

export function GET() {
  return new NextResponse(JSON.stringify(manifestDefinition()), {
    headers: { "Content-Type": "application/manifest+json" },
  });
}
