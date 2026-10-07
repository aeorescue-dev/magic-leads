import { describe, expect, it } from "vitest";

import {
  formatStageRemaining,
  severityFor,
  stageIndex,
  stageRemainingMs,
  syncClock,
  STAGE_ORDER,
} from "./stage-countdown";

describe("formatStageRemaining", () => {
  it("formata zero/negativo como 00:00", () => {
    expect(formatStageRemaining(0)).toBe("00:00");
    expect(formatStageRemaining(-500)).toBe("00:00");
  });

  it("usa 59:32 para menos de 1 hora", () => {
    expect(formatStageRemaining(59 * 60 * 1000 + 32 * 1000)).toBe("59:32");
    expect(formatStageRemaining(30 * 1000)).toBe("00:30");
    expect(formatStageRemaining(45 * 60 * 1000)).toBe("45:00");
    expect(formatStageRemaining(60 * 60 * 1000 - 1)).toBe("59:59");
  });

  it("usa 47h 12m a partir de 1 hora", () => {
    expect(formatStageRemaining(60 * 60 * 1000)).toBe("1h 00m");
    expect(formatStageRemaining((47 * 60 + 12) * 60 * 1000)).toBe("47h 12m");
    expect(formatStageRemaining((48 * 60 * 60 + 7 * 60) * 1000)).toBe("48h 07m");
  });
});

describe("severityFor", () => {
  it("nivel normal acima de 6h", () => {
    expect(severityFor(7 * 60 * 60 * 1000)).toBe("normal");
    expect(severityFor(48 * 60 * 60 * 1000)).toBe("normal");
  });

  it("warning ate 6h", () => {
    expect(severityFor(6 * 60 * 60 * 1000)).toBe("warning");
    expect(severityFor(5 * 60 * 60 * 1000)).toBe("warning");
  });

  it("critical ate 1h", () => {
    expect(severityFor(60 * 60 * 1000)).toBe("critical");
    expect(severityFor(59 * 60 * 1000)).toBe("critical");
    expect(severityFor(0)).toBe("critical");
  });
});

describe("stageIndex / STAGE_ORDER", () => {
  it("mantem a ordem das fases 1h/48h/48h", () => {
    expect(STAGE_ORDER).toEqual(["reserved", "contacted", "in_negotiation", "converted"]);
  });

  it("converte fase para indice", () => {
    expect(stageIndex("reserved")).toBe(0);
    expect(stageIndex("contacted")).toBe(1);
    expect(stageIndex("in_negotiation")).toBe(2);
    expect(stageIndex("converted")).toBe(3);
    expect(stageIndex(undefined)).toBe(0);
  });
});

describe("stageRemainingMs / syncClock", () => {
  it("sem prazo devolve 0", () => {
    expect(stageRemainingMs(undefined)).toBe(0);
    expect(stageRemainingMs("não-é-data")).toBe(0);
  });

  it("prazo no passado devolve 0", () => {
    expect(stageRemainingMs(new Date(Date.now() - 5000).toISOString())).toBe(0);
  });

  it("syncClock guarda o desvio do relogio do servidor", () => {
    const offset = syncClock(new Date(Date.now() + 5 * 60 * 1000).toISOString());
    expect(Math.abs(offset - 300000)).toBeLessThan(5000);
  });
});