// Cart totals for the shop UI. Prices are dollars (e.g. 19.99).

export function cartTotal(items) {
  // items: [{ price: number, qty: number }] — returns the total in dollars.
  let total = 0;
  for (const item of items) {
    total += item.price * item.qty;
  }
  return total;
}

export function formatTotal(items) {
  // What the UI renders, e.g. "$19.99".
  return `$${cartTotal(items).toFixed(2)}`;
}
