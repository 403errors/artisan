import assert from "node:assert/strict";
import test from "node:test";

import { cartTotal, formatTotal } from "../cart.js";

test("integer prices sum exactly", () => {
  assert.equal(cartTotal([{ price: 10, qty: 2 }, { price: 5, qty: 1 }]), 25);
});

test("empty cart is zero", () => {
  assert.equal(cartTotal([]), 0);
});

test("formatTotal renders two decimals", () => {
  assert.equal(formatTotal([{ price: 19, qty: 1 }]), "$19.00");
});
