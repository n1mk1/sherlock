import { describe, expect, it } from "vitest";
import { formatCell, formatNumber, isPctColumn } from "./format";

describe("formatting", () => {
  it("formats like the server's chips", () => {
    expect(formatNumber(0.7274, true)).toBe("72.7%");
    expect(formatNumber(1025982.16)).toBe("1,025,982");
    expect(formatNumber(87.509)).toBe("87.51");
    expect(formatNumber(1309)).toBe("1,309");
    expect(formatCell(null)).toBe("—");
    expect(isPctColumn("survival_rate", [0.2, 0.7])).toBe(true);
    expect(isPctColumn("survival_rate", [12])).toBe(false);
    expect(isPctColumn("fare", [0.5])).toBe(false);
  });
});
