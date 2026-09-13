(() => {
  const form = document.querySelector("#invoice-form");
  if (!form) return;

  const bodyStates = JSON.parse(document.body.dataset.states || "{}");
  const stateCodes = Object.fromEntries(Object.entries(bodyStates).map(([code, name]) => [name, code]));
  const submitButton = document.querySelector("#generate-button");
  const sellerState = document.querySelector("#seller-state");
  const buyerState = document.querySelector("#buyer-state");
  const placeOfSupply = document.querySelector("#place-of-supply");
  const gstinPattern = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

  function messageElement(input) {
    let message = input.parentElement.querySelector(".client-gstin-error");
    if (!message) {
      message = document.createElement("p");
      message.className = "field-error client-gstin-error";
      input.parentElement.append(message);
    }
    return message;
  }

  function validateGstin(input, stateSelect, required) {
    const value = input.value.trim().toUpperCase();
    input.value = value;
    let error = "";
    if (!value && required) error = "GSTIN is required.";
    else if (value && !gstinPattern.test(value)) error = "Enter a valid 15-character GSTIN.";
    else if (value && stateSelect.value && stateCodes[stateSelect.value] !== value.slice(0, 2)) error = "GSTIN state code must match the selected state.";
    input.setCustomValidity(error);
    input.classList.toggle("invalid", Boolean(error));
    const message = messageElement(input);
    message.textContent = error;
  }

  function validateAll() {
    validateGstin(form.elements.seller_gstin, sellerState, true);
    validateGstin(form.elements.buyer_gstin, buyerState, false);
    submitButton.disabled = !form.checkValidity();
  }

  function syncPlaceOfSupply() {
    if (!placeOfSupply.value && buyerState.value) placeOfSupply.value = buyerState.value;
  }

  function removeLine(button) {
    const rows = document.querySelectorAll(".line-item");
    if (rows.length === 1) {
      const firstInput = rows[0].querySelector("input[name='description']");
      rows[0].querySelectorAll("input").forEach((input) => {
        if (input.name === "quantity") input.value = "1";
        else input.value = "";
      });
      rows[0].querySelector("select[name='gst_rate']").value = "18";
      firstInput.focus();
    } else {
      button.closest("tr").remove();
    }
    validateAll();
    window.updateInvoiceTotals?.();
  }

  document.querySelector("#add-line").addEventListener("click", () => {
    const fragment = document.querySelector("#line-template").content.cloneNode(true);
    document.querySelector("#line-items").append(fragment);
    const added = document.querySelector("#line-items tr:last-child input[name='description']");
    added.focus();
    validateAll();
    window.updateInvoiceTotals?.();
  });

  document.querySelector("#line-items").addEventListener("click", (event) => {
    const button = event.target.closest(".remove-line");
    if (button) removeLine(button);
  });

  form.addEventListener("input", validateAll);
  form.addEventListener("change", (event) => {
    if (event.target === buyerState) syncPlaceOfSupply();
    validateAll();
  });
  form.addEventListener("submit", (event) => {
    validateAll();
    if (!form.checkValidity()) {
      event.preventDefault();
      form.reportValidity();
    }
  });

  syncPlaceOfSupply();
  validateAll();
})();
