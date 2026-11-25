(() => {
  const form = document.querySelector("#invoice-form");
  if (!form) return;

  const roundMoney = (value) => Math.round((Number(value) + Number.EPSILON) * 100) / 100;
  const numericValue = (row, field) => {
    const value = Number(row.querySelector(`[name="${field}"]`)?.value);
    return Number.isFinite(value) ? value : 0;
  };
  const money = (value) => new Intl.NumberFormat("en-IN", {
    style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(roundMoney(value));
  const write = (id, value) => { document.querySelector(id).textContent = money(value); };

  function taxMode() {
    const seller = document.querySelector("#seller-state")?.value;
    const place = document.querySelector("#place-of-supply")?.value;
    if (!seller || !place) return null;
    return seller === place ? "intra" : "inter";
  }

  function updateTaxBadge(mode) {
    const badge = document.querySelector("#tax-mode-badge");
    const message = document.querySelector("#tax-mode-message");
    badge.className = "tax-badge";
    if (mode === "intra") {
      badge.textContent = "CGST + SGST";
      badge.classList.add("intra");
      message.textContent = "Intra-state supply";
    } else if (mode === "inter") {
      badge.textContent = "IGST";
      badge.classList.add("inter");
      message.textContent = "Inter-state supply";
    } else {
      badge.textContent = "Select states";
      message.textContent = "Tax treatment will update automatically.";
    }
  }

  function updateInvoiceTotals() {
    const mode = taxMode();
    let taxable = 0;
    let cgst = 0;
    let sgst = 0;
    let igst = 0;

    document.querySelectorAll(".line-item").forEach((row) => {
      const quantity = numericValue(row, "quantity");
      const unitPrice = numericValue(row, "unit_price");
      const rate = numericValue(row, "gst_rate");
      const lineCell = row.querySelector(".line-amount-cell");
      if (quantity <= 0 || unitPrice < 0 || rate < 0) {
        if (lineCell) lineCell.textContent = money(0);
        return;
      }
      const lineTaxable = roundMoney(quantity * unitPrice);
      if (lineCell) lineCell.textContent = money(lineTaxable);
      taxable += lineTaxable;
      if (mode === "intra") {
        // Match the server: CGST and SGST are each rounded on the line.
        cgst += roundMoney(lineTaxable * rate / 200);
        sgst += roundMoney(lineTaxable * rate / 200);
      } else if (mode === "inter") {
        igst += roundMoney(lineTaxable * rate / 100);
      }
    });

    taxable = roundMoney(taxable);
    cgst = roundMoney(cgst);
    sgst = roundMoney(sgst);
    igst = roundMoney(igst);
    write("#taxable-total", taxable);
    write("#cgst-total", cgst);
    write("#sgst-total", sgst);
    write("#igst-total", igst);
    write("#grand-total", taxable + cgst + sgst + igst);
    updateTaxBadge(mode);
  }

  form.addEventListener("input", updateInvoiceTotals);
  form.addEventListener("change", updateInvoiceTotals);
  window.updateInvoiceTotals = updateInvoiceTotals;
  updateInvoiceTotals();
})();
