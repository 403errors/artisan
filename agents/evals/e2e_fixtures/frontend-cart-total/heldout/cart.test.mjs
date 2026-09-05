// Held-out oracle tests — injected by the eval harness AFTER the pipeline finishes, never
// visible to the coding agent. They fail on the seeded bug and pass on a correct fix.

import assert from "node:assert/strict";
import test from "node:test";

import { cartTotal, formatTotal } from "../cart.js";

test("three 10-cent items total exactly 0.3", () => {
  assert.equal(cartTotal([{ price: 0.1, qty: 3 }]), 0.3);
});

test("mixed cents total is exact", () => {
  const items = [
    { price: 0.1, qty: 1 },
    { price: 0.2, qty: 1 },
    { price: 19.99, qty: 2 },
  ];
  assert.equal(cartTotal(items), 40.28);
});

test("formatTotal never shows float artifacts", () => {
  assert.equal(formatTotal([{ price: 0.1, qty: 3 }]), "$0.30");
});
