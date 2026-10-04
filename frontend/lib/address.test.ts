import { describe, expect, it } from "vitest";

import { buildFullAddress } from "./address";

/**
 * O `address` legado embebe a cidade e o estado ("RUA, NYC, NY") e a cidade
 * existe tambem como coluna. Concatenar as duas coisas produzia
 * "RUA, NYC, NY, NYC" em 100% dos leads. `buildFullAddress` so acrescenta a
 * cidade quando ela ainda nao esta no address.
 */
describe("buildFullAddress", () => {
  it("NAO repete a cidade quando o address ja a contem (caso legado)", () => {
    expect(buildFullAddress("854 EAST NEW YORK AVENUE, NYC, NY", "NYC")).toBe(
      "854 EAST NEW YORK AVENUE, NYC, NY",
    );
  });

  it("acrescenta a cidade quando o address e so a rua (caso novo)", () => {
    expect(buildFullAddress("448 WEST 54 STREET", "NYC")).toBe("448 WEST 54 STREET, NYC");
  });

  it("acrescenta a cidade mesmo que o address contenha o estado", () => {
    expect(buildFullAddress("124-16 ROCKAWAY BEACH BOULEVARD, NY", "NYC")).toBe(
      "124-16 ROCKAWAY BEACH BOULEVARD, NY, NYC",
    );
  });

  it("ignora a caixa e os acentos ao comparar", () => {
    expect(buildFullAddress("200 MAIN ST, SAO PAULO", "sao paulo")).toBe("200 MAIN ST, SAO PAULO");
  });

  it("preserva a unidade de apartamento", () => {
    expect(buildFullAddress("1000 SIMPSON STREET, APT 4F", "NYC")).toBe(
      "1000 SIMPSON STREET, APT 4F, NYC",
    );
  });

  it("nao inventa separadores quando a cidade falta", () => {
    expect(buildFullAddress("448 WEST 54 STREET", null)).toBe("448 WEST 54 STREET");
    expect(buildFullAddress("448 WEST 54 STREET", "")).toBe("448 WEST 54 STREET");
  });

  it("devolve so a cidade quando nao ha address", () => {
    expect(buildFullAddress(null, "Chicago")).toBe("Chicago");
    expect(buildFullAddress("", "Chicago")).toBe("Chicago");
  });

  it("aguenta address e cidade ausentes", () => {
    expect(buildFullAddress(null, null)).toBe("");
    expect(buildFullAddress(undefined, undefined)).toBe("");
  });

  it("nao deixa virgula pendurada a meio", () => {
    expect(buildFullAddress("448 WEST 54 STREET,", "NYC")).toBe("448 WEST 54 STREET, NYC");
  });

  it("nao duplica quando a cidade e igual ao proprio address", () => {
    expect(buildFullAddress("BROOKLYN", "Brooklyn")).toBe("BROOKLYN");
  });
});
