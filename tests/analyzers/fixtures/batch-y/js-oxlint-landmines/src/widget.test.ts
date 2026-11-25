import { vi } from "vitest";

vi.mock("./api");

it("waits", async () => {
  await new Promise((resolve) => setTimeout(resolve, 50));
});

it.each([{ retries: 2 }])("retries", () => {});