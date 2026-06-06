// Elements
const searchInput = document.getElementById('medicineSearch');
const searchResults = document.getElementById('search-results');
const billTableBody = document.querySelector('#bill-table-body');
const subtotalSpan = document.getElementById('subtotal');
const discountInput = document.getElementById('discount');
// const taxInput = document.getElementById('tax'); // REMOVED: Tax element
const billTotalSpan = document.getElementById('bill-total');
const generateBillBtn = document.getElementById('generate-bill-btn');
const printBillBtn = document.getElementById('print-bill-btn');
const statusMessage = document.getElementById('status-message');
const resetBillBtn = document.getElementById('reset-bill-btn');
const customerNameInput = document.getElementById('customer-name');
const doctorNameInput = document.getElementById('doctor-name');
const customerPhoneInput = document.getElementById('customer-phone');
const customerAddressInput = document.getElementById('customer-address');

// Store each line independently using a unique key
let billItems = {};
let isPrinting = false; // Flag to manage print process state

// --- Session Storage Functions ---
const STORAGE_KEY = 'currentBillItems';

function saveBillToSession() {
    // Only save if there are items or if discount field is populated
    if (Object.keys(billItems).length > 0 || parseFloat(discountInput.value) > 0) {
        try {
            sessionStorage.setItem(STORAGE_KEY, JSON.stringify(billItems));
            sessionStorage.setItem('billDiscount', discountInput.value);
            // Save customer details
            sessionStorage.setItem('customerName', customerNameInput.value || '');
            sessionStorage.setItem('doctorName', doctorNameInput.value || '');
            sessionStorage.setItem('customerPhone', customerPhoneInput.value || '');
            sessionStorage.setItem('customerAddress', customerAddressInput.value || '');
        } catch (e) {
            console.warn("Session storage failed: ", e);
        }
    }
}

function loadBillFromSession() {
    try {
        const storedItems = sessionStorage.getItem(STORAGE_KEY);
        const storedDiscount = sessionStorage.getItem('billDiscount');
        // Tax removed from session load

        if (storedItems && storedItems !== '{}') {
            billItems = JSON.parse(storedItems);

            // Load and populate fields
            if (storedDiscount) discountInput.value = storedDiscount;

            customerNameInput.value = sessionStorage.getItem('customerName') || '';
            doctorNameInput.value = sessionStorage.getItem('doctorName') || '';
            customerPhoneInput.value = sessionStorage.getItem('customerPhone') || '';
            customerAddressInput.value = sessionStorage.getItem('customerAddress') || '';

            updateBillTable();
            return true;
        }
    } catch (e) {
        console.error("Error loading bill from session:", e);
        sessionStorage.removeItem(STORAGE_KEY); // Clear potentially corrupted item data
    }
    return false;
}

function clearBillSession() {
    sessionStorage.removeItem(STORAGE_KEY);
    sessionStorage.removeItem('billDiscount');
    sessionStorage.removeItem('customerName');
    sessionStorage.removeItem('doctorName');
    sessionStorage.removeItem('customerPhone');
    sessionStorage.removeItem('customerAddress');
}
// ---------------------------------

function makeLineId() {
    return (crypto.randomUUID && crypto.randomUUID()) || (Date.now() + '-' + Math.random().toString(36).slice(2));
}

// Function to perform the search and populate results dropdown
async function performSearch() {
    const query = searchInput.value.trim();
    searchResults.innerHTML = '';
    if (query.length > 1) {
        try {
            // Live search (expects backend to return id, name, unit, mrp, loose_unit, loose_mrp, stock)
            const resp = await fetch(`/search_medicine?query=${encodeURIComponent(query)}`);
            const medicines = await resp.json();

            // Display dropdown and populate results
            searchResults.style.display = 'block';
            medicines.forEach(item => {
                const div = document.createElement('div');
                div.classList.add('search-result-item');
                // Store the full item data in an attribute for quick access on click/Enter
                div.setAttribute('data-item', JSON.stringify(item));
                div.textContent = `${item.name} (${item.unit || '-'})`;

                div.addEventListener('click', () => {
                    // Use the stored data to add the item
                    const itemData = JSON.parse(div.getAttribute('data-item'));
                    addItemToBill(itemData);
                    searchInput.value = '';
                    searchResults.innerHTML = '';
                    searchResults.style.display = 'none';
                    searchInput.focus(); // Keep focus on the search box
                });
                searchResults.appendChild(div);
            });
        } catch (e) {
            console.error('Error fetching search results:', e);
        }
    } else {
        searchResults.style.display = 'none';
    }
}

// Event listener for input (live search)
searchInput.addEventListener('input', performSearch);

// Event listener for Enter key (quick add)
searchInput.addEventListener('keydown', (e) => {
    // Only run if the key pressed is Enter
    if (e.key === 'Enter') {
        e.preventDefault(); // Stop default form submission or newline

        const firstResult = searchResults.querySelector('.search-result-item');

        if (firstResult) {
            try {
                // Grab data from the first visible result and add to bill
                const itemData = JSON.parse(firstResult.getAttribute('data-item'));
                addItemToBill(itemData);

                // Clear input and hide results
                searchInput.value = '';
                searchResults.innerHTML = '';
                searchResults.style.display = 'none';
            } catch (error) {
                console.error("Error parsing item data:", error);
            }
        } else if (searchInput.value.trim().length > 1) {
            // If Enter is pressed but no results are displayed, re-run search
            performSearch();
        }
    }
});


// Hide search results when clicking outside the search container
document.addEventListener('click', (event) => {
    const isClickInside = searchInput.parentElement.contains(event.target);
    if (!isClickInside) {
        searchResults.style.display = 'none';
    }
});

function addItemToBill(item) {
    const lineId = makeLineId();

    // Check if already added
    const existingKey = Object.keys(billItems).find(
        k => billItems[k].id === item.id && billItems[k].unitType === 'pack'
    );

    if (existingKey) {
        billItems[existingKey].quantity++;
    } else {
        // ✅ Strict priority for backend loose_mrp value
        let correctLooseMrp = 0;
        if (item.loose_mrp && Number(item.loose_mrp) > 0) {
            correctLooseMrp = Number(item.loose_mrp);
        } else if (item.loose_basic_price && Number(item.loose_basic_price) > 0) {
            correctLooseMrp = Number(item.loose_basic_price);
        } 
        // 🛑 CRITICAL CHANGE: Removed the automatic division calculation here.
        // The Loose MRP must come from stored data only.
        // else if (item.mrp && item.pack_size_ml > 0) {
        //     correctLooseMrp = Number(item.mrp) / Number(item.pack_size_ml);
        // }

        billItems[lineId] = {
            lineId,
            id: item.id,
            name: item.name,
            unit: item.unit,
            unitType: 'pack',
            mrp: Number(item.mrp) || 0,
            loose_unit: item.loose_unit,
            loose_mrp: Number(correctLooseMrp.toFixed(2)) || 0,
            pack_size_ml: item.pack_size_ml,
            loose_size_ml: item.loose_size_ml,
            quantity: 1,
            subtotal: 0
        };
    }

    updateBillTable();
    saveBillToSession();
}

/**
 * Recalculates the subtotal for a specific item line based on its current quantity and unit type,
 * updates the item in billItems, and updates the DOM elements for that row.
 * @param {string} key - The unique key of the item in billItems.
 * @param {HTMLTableRowElement} row - The DOM element for the row.
 */
function updateItemLine(key, row) {
    const item = billItems[key];
    const unitSelect = row.querySelector('.unit-select');
    const qtyInput = row.querySelector('.qty-input');
    const priceInput = row.querySelector('.price-input');
    const subtotalSpan = row.querySelector('.subtotal-span');

    const newType = unitSelect.value;

    // 1. Read and sanitize user input for price and quantity
    // Allow reading price directly from input now that it's editable
    let newPrice = parseFloat(priceInput.value) || 0;
    const newQty = Math.max(1, parseInt(qtyInput.value) || 1);

    // Ensure price is not negative and has two decimal places for display
    newPrice = Math.max(0, newPrice);
    priceInput.value = newPrice.toFixed(2);
    qtyInput.value = newQty;

    // 2. Update the item object state (Crucial for persistence and backend)
    item.unitType = newType;
    item.quantity = newQty;

    // The price user inputs updates the corresponding mrp/loose_mrp property
    if (newType === 'loose') {
        item.loose_mrp = newPrice;
    } else {
        item.mrp = newPrice;
    }

    // 3. Calculate and update subtotal
    const newSubtotal = newQty * newPrice;
    item.subtotal = newSubtotal;

    // 4. Update the DOM elements
    subtotalSpan.textContent = newSubtotal.toFixed(2);

    updateTotal();
    saveBillToSession();
}

function updateBillTable() {
    const searchRow = document.getElementById('search-row');
    let serialNo = 1;

    billTableBody.innerHTML = '';

    Object.keys(billItems).forEach(key => {
        const item = billItems[key];
        const row = document.createElement('tr');
        row.setAttribute('data-key', key);

        const isLoose = item.unitType === 'loose';
        const currentPrice = isLoose ? item.loose_mrp : item.mrp;
        const subtotal = (Number(currentPrice) || 0) * item.quantity;
        item.subtotal = subtotal;

        row.innerHTML = `
            <td>${serialNo++}</td>
            <td>${item.name}</td>
            <td>
                <select class="unit-select">
                    <option value="pack" ${isLoose ? '' : 'selected'}>
                        Pack (${item.unit || '-'})
                    </option>
                    <option value="loose" ${isLoose ? 'selected' : ''}>
                        Loose (${item.loose_unit || '-'})
                    </option>
                </select>
            </td>
            <td>
                ₹<input type="number" class="price-input" value="${(Number(currentPrice) || 0).toFixed(2)}" min="0.01" step="0.01">
            </td>
            <td><input type="number" class="qty-input" value="${item.quantity}" min="1" max="999"></td>
            <td>₹<span class="subtotal-span">${subtotal.toFixed(2)}</span></td>
            <td><button class="remove-btn btn-danger">Remove</button></td>
        `;

        const unitSelect = row.querySelector('.unit-select');
        const qtyInput = row.querySelector('.qty-input');
        const priceInput = row.querySelector('.price-input');
        const removeBtn = row.querySelector('.remove-btn');

        // Quantity listeners
        qtyInput.addEventListener('input', () => updateItemLine(key, row));
        qtyInput.addEventListener('change', () => updateItemLine(key, row));

        // Price listeners (manual edits)
        priceInput.addEventListener('input', () => updateItemLine(key, row));
        priceInput.addEventListener('change', () => updateItemLine(key, row));

        // ✅ Fixed: Always use backend prices on unit switch
        unitSelect.addEventListener('change', () => {
            const newType = unitSelect.value;

            const newDefaultPrice = newType === 'loose'
                ? (Number(item.loose_mrp) || 0)
                : (Number(item.mrp) || 0);

            priceInput.value = newDefaultPrice.toFixed(2);
            item.unitType = newType; // keep current selection
            updateItemLine(key, row);
        });

        removeBtn.addEventListener('click', () => {
            delete billItems[row.getAttribute('data-key')];
            updateBillTable();
            saveBillToSession();
        });

        billTableBody.appendChild(row);
    });

    if (searchRow) {
        billTableBody.prepend(searchRow);
        searchInput.focus();
    }

    updateTotal();
}


function updateTotal() {
    // Re-calculate the subtotal based on the stored subtotal property of each item
    const rawSubtotal = Object.values(billItems).reduce((sum, it) => sum + (Number(it.subtotal) || 0), 0);
    subtotalSpan.textContent = rawSubtotal.toFixed(2);

    let total = rawSubtotal;
    const discount = parseFloat(discountInput.value) || 0;

    if (discount > 0) {
        // Apply discount percentage
        total = total * (1 - discount / 100);
    }
    // Tax calculation REMOVED

    billTotalSpan.textContent = total.toFixed(2);
}

/**
 * Resets all bill-related data, UI inputs, and clears session storage.
 */
function resetBillUI() {
    billItems = {};
    updateBillTable(); // Clears table body and updates total to 0.00

    // Clear inputs
    discountInput.value = 0;
    customerNameInput.value = '';
    doctorNameInput.value = '';
    customerPhoneInput.value = '';
    customerAddressInput.value = ''; // Clear address

    statusMessage.textContent = '';
    clearBillSession(); // Clear session storage on reset
    searchInput.focus();
}

// Add event listener to save state on discount input changes
discountInput.addEventListener('input', () => {
    updateTotal();
    saveBillToSession();
});

resetBillBtn.addEventListener('click', resetBillUI);

async function saveAndProcessBill(shouldPrint) {
    if (Object.keys(billItems).length === 0) {
        statusMessage.textContent = "Please add items to the bill.";
        statusMessage.style.color = "red";
        setTimeout(() => (statusMessage.textContent = ''), 3000);
        return;
    }

    const paymentMethod = document.querySelector('input[name="payment-method"]:checked').value;

    // Gather customer/doctor details
    const customerName = customerNameInput.value || '';
    const doctorName = doctorNameInput.value || '';
    const customerPhone = customerPhoneInput.value || '';
    const customerAddress = customerAddressInput.value || '';

    // 1. Update printable bill details BEFORE the async database call
    document.getElementById('bill-customer-name').textContent = customerName;
    document.getElementById('bill-doctor-name').textContent = doctorName;
    document.getElementById('bill-customer-phone').textContent = customerPhone;

    // 2. Prepare print action (only opens dialog, does not clear state yet)
    if (shouldPrint) {
        isPrinting = true;
        // Open the print dialog immediately
        setTimeout(() => {
            window.print();
            isPrinting = false;
        }, 200);
    }

    // 3. Prepare data for backend
    const itemsForBackend = Object.values(billItems).map(it => ({
        id: it.id,
        name: it.name,
        unit_type: it.unitType,
        // Send the stored unit price (mrp or loose_mrp) which now reflects user edits
        unit_price: it.unitType === 'loose' ? it.loose_mrp : it.mrp,
        quantity: it.quantity
    }));

    const billData = {
        items: itemsForBackend,
        total: parseFloat(billTotalSpan.textContent),
        payment_method: paymentMethod,
        discount: parseFloat(discountInput.value) || 0,
        // tax: 0, // Tax removed
        customer_name: customerName,
        doctor_name: doctorName,
        customer_phone: customerPhone,
        customer_address: customerAddress
    };

    // 4. Send data to backend
    try {
        const resp = await fetch('/generate_bill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(billData)
        });
        const result = await resp.json();

        if (resp.ok) {
            statusMessage.textContent = result.message || 'Bill generated.';
            statusMessage.style.color = 'green';

            // If it's a regular save, clear everything immediately and REDIRECT
            if (!shouldPrint) {
                resetBillUI();
                // FIX: Use the global variable defined in billing.html
                window.location.href = DASHBOARD_URL; 
            }

        } else {
            statusMessage.textContent = `Error: ${result.message || 'Failed to generate bill.'}`;
            statusMessage.style.color = 'red';
        }
    } catch (e) {
        statusMessage.textContent = 'An unexpected network error occurred.';
        statusMessage.style.color = 'red';
    } finally {
        setTimeout(() => (statusMessage.textContent = ''), 5000);
    }
}

generateBillBtn.addEventListener('click', () => saveAndProcessBill(false));
printBillBtn.addEventListener('click', () => saveAndProcessBill(true));

// --- Global Event Listeners for Persistence ---

// 2. Save bill just before the user leaves the page
window.addEventListener('beforeunload', (e) => {
    // If we're printing, return and do nothing. The session data must remain intact.
    if (isPrinting) {
        return;
    }

    // Save state if items exist, otherwise clear session.
    if (Object.keys(billItems).length > 0) {
        saveBillToSession();
    } else {
        clearBillSession();
    }
});

// 3. Clear session upon returning to the window after a print job is done or cancelled.
window.addEventListener('focus', () => {
    if (isPrinting) {
        // This runs when the browser window regains focus after the print dialog is closed (Print or Cancel).
        isPrinting = false;
        // Clear the data and reload the page to get a fresh bill number and reset the screen.
        clearBillSession();
        window.location.reload();
    }
});

document.addEventListener('DOMContentLoaded', () => {
    // Only load if we are not editing a bill
    if (Object.keys(billItems).length === 0) {
        loadBillFromSession();
    }
});