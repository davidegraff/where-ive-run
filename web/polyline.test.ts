import { expect, it } from "vitest";
import { decodePolyline } from "./polyline.ts";

it("decodes Google's documented example polyline", () => {
  // The same string is checked against the server's encoder in tests/test_ingest.py.
  expect(decodePolyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")).toEqual([[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]]);
});
