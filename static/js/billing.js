// Elements
const searchInput = document.getElementById('medicineSearch');
const searchResults = document.getElementById('search-results');
const billTableBody = document.querySelector('#bill-table-body');
const subtotalSpan = document.getElementById('subtotal');
const discountInput = document.getElementById('discount');
const billTotalSpan = document.getElementById('bill-total');
const generateBillBtn = document.getElementById('generate-bill-btn');
const printBillBtn = document.getElementById('print-bill-btn');
const statusMessage = document.getElementById('status-message');
const resetBillBtn = document.getElementById('reset-bill-btn');
const customerNameInput = document.getElementById('customer-name');
const doctorNameInput = document.getElementById('doctor-name');
const customerPhoneInput = document.getElementById('customer-phone');
const customerAddressInput = document.getElementById('customer-address');
const customerHistoryInfo = document.getElementById('customer-history-info');

// Modal elements
const qtyModalOverlay = document.getElementById('qtyModalOverlay');
const modalMedName = document.getElementById('modalMedName');
const modalMedCode = document.getElementById('modalMedCode');
const modalStockBanner = document.getElementById('modalStockBanner');
const modalStockValue = document.getElementById('modalStockValue');
const modalUnitType = document.getElementById('modalUnitType');
const modalQty = document.getElementById('modalQty');
const modalSubtotal = document.getElementById('modalSubtotal');
const modalCancelBtn = document.getElementById('modalCancelBtn');
const modalAddBtn = document.getElementById('modalAddBtn');

// Store each line independently using a unique key
let billItems = {};
let isPrinting = false; // Flag to manage print process state
let currentModalItem = null; // Store current item being configured in modal

// Simple debounce helper
function debounce(func, wait) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

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
                
                const stockVal = Number(item.stock) || 0;
                const packSize = Number(item.pack_size_ml) || 1;
                const packsLeft = packSize > 0 ? (stockVal / packSize).toFixed(1) : 0;
                
                div.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                        <div>
                            <strong style="color: var(--primary-text); font-weight: 600;">${item.name}</strong> 
                            <span style="font-size: 0.82em; color: var(--secondary-text); margin-left: 8px;">Code: ${item.code || '-'}</span>
                        </div>
                        <div style="font-size: 0.88em; text-align: right;">
                            <span style="margin-right: 15px;">Stock: <span style="font-weight: 600; color: ${stockVal <= 0 ? 'var(--danger-color)' : (packsLeft < 5 ? 'var(--secondary-color)' : 'var(--success-color)')}">${packsLeft} ${item.unit || 'packs'}</span></span>
                            <span style="font-weight: 700; color: var(--info-hover);">₹${Number(item.mrp).toFixed(2)}</span>
                        </div>
                    </div>
                `;

                div.addEventListener('click', () => {
                    const itemData = JSON.parse(div.getAttribute('data-item'));
                    searchInput.value = '';
                    searchResults.innerHTML = '';
                    searchResults.style.display = 'none';
                    openQtyModal(itemData);
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

// Event listener for Enter key (quick add opens modal)
searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();

        const firstResult = searchResults.querySelector('.search-result-item');

        if (firstResult) {
            try {
                const itemData = JSON.parse(firstResult.getAttribute('data-item'));
                searchInput.value = '';
                searchResults.innerHTML = '';
                searchResults.style.display = 'none';
                openQtyModal(itemData);
            } catch (error) {
                console.error("Error parsing item data:", error);
            }
        } else if (searchInput.value.trim().length > 1) {
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

function addItemToBill(item, quantity = 1, unitType = 'pack') {
    // Check if already added with the exact same unitType
    const existingKey = Object.keys(billItems).find(
        k => billItems[k].id === item.id && billItems[k].unitType === unitType
    );

    if (existingKey) {
        billItems[existingKey].quantity += quantity;
    } else {
        let correctLooseMrp = 0;
        if (item.loose_mrp && Number(item.loose_mrp) > 0) {
            correctLooseMrp = Number(item.loose_mrp);
        } else if (item.loose_basic_price && Number(item.loose_basic_price) > 0) {
            correctLooseMrp = Number(item.loose_basic_price);
        } 

        const lineId = makeLineId();
        billItems[lineId] = {
            lineId,
            id: item.id,
            name: item.name,
            unit: item.unit,
            unitType: unitType,
            mrp: Number(item.mrp) || 0,
            loose_unit: item.loose_unit,
            loose_mrp: Number(correctLooseMrp.toFixed(2)) || 0,
            pack_size_ml: item.pack_size_ml,
            loose_size_ml: item.loose_size_ml,
            stock: Number(item.stock) || 0,
            code: item.code || '',
            quantity: quantity,
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
    let newPrice = parseFloat(priceInput.value) || 0;
    const newQty = Math.max(1, parseInt(qtyInput.value) || 1);

    newPrice = Math.max(0, newPrice);
    priceInput.value = newPrice.toFixed(2);
    qtyInput.value = newQty;

    // 2. Update the item object state
    item.unitType = newType;
    item.quantity = newQty;

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

    // 5. Update stock available display text and warning badge inline
    const stock = Number(item.stock) || 0;
    const packSize = Number(item.pack_size_ml) || 1;
    const looseSize = Number(item.loose_size_ml) || 1;
    
    let availableStockText = "";
    let isLowOrOut = false;
    
    if (newType === 'loose') {
        const looseQty = looseSize > 0 ? (stock / looseSize) : 0;
        availableStockText = `${looseQty.toFixed(1)} ${item.loose_unit || 'units'}`;
        isLowOrOut = newQty > looseQty;
    } else {
        const packQty = packSize > 0 ? (stock / packSize) : 0;
        availableStockText = `${packQty.toFixed(1)} ${item.unit || 'packs'}`;
        isLowOrOut = newQty > packQty;
    }
    
    const stockValSpan = row.querySelector('.stock-value-span');
    if (stockValSpan) {
        stockValSpan.textContent = availableStockText;
    }
    
    const stockCell = stockValSpan ? stockValSpan.parentElement : null;
    if (stockCell) {
        const badge = stockCell.querySelector('.stock-alert-badge');
        if (badge) badge.remove();
        
        if (isLowOrOut) {
            row.classList.add('over-stock-limit');
            stockCell.insertAdjacentHTML('beforeend', ' <span class="stock-alert-badge">⚠ Exceeds</span>');
        } else {
            row.classList.remove('over-stock-limit');
        }
    }

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

        // Calculate available stock based on selected unit type
        const stock = Number(item.stock) || 0;
        const packSize = Number(item.pack_size_ml) || 1;
        const looseSize = Number(item.loose_size_ml) || 1;
        
        let availableStockText = "";
        let isLowOrOut = false;
        
        if (isLoose) {
            const looseQty = looseSize > 0 ? (stock / looseSize) : 0;
            availableStockText = `${looseQty.toFixed(1)} ${item.loose_unit || 'units'}`;
            isLowOrOut = item.quantity > looseQty;
        } else {
            const packQty = packSize > 0 ? (stock / packSize) : 0;
            availableStockText = `${packQty.toFixed(1)} ${item.unit || 'packs'}`;
            isLowOrOut = item.quantity > packQty;
        }

        if (isLowOrOut) {
            row.classList.add('over-stock-limit');
        } else {
            row.classList.remove('over-stock-limit');
        }

        const stockWarningSpan = isLowOrOut ? ' <span class="stock-alert-badge">⚠ Exceeds</span>' : '';

        row.innerHTML = `
            <td>${serialNo++}</td>
            <td>
                <span style="font-weight: 500;">${item.name}</span>
                ${item.code ? `<div style="font-size: 0.8em; color: var(--secondary-text);">Code: ${item.code}</div>` : ''}
            </td>
            <td>
                <select class="unit-select">
                    <option value="pack" ${isLoose ? '' : 'selected'}>
                        Pack (${item.unit || '-'})
                    </option>
                    ${item.loose_unit ? `
                    <option value="loose" ${isLoose ? 'selected' : ''}>
                        Loose (${item.loose_unit})
                    </option>
                    ` : ''}
                </select>
            </td>
            <td>
                ₹<input type="number" class="price-input" value="${(Number(currentPrice) || 0).toFixed(2)}" min="0.01" step="0.01">
            </td>
            <td><input type="number" class="qty-input" value="${item.quantity}" min="1" max="999"></td>
            <td class="no-print">
                <span class="stock-value-span">${availableStockText}</span>
                ${stockWarningSpan}
            </td>
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

        // Always use backend prices on unit switch
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

// Check for stock validation issues before saving the bill
function hasStockErrors() {
    let hasError = false;
    let errorMsg = "";
    
    for (const key of Object.keys(billItems)) {
        const item = billItems[key];
        
        // Skip check if stock details are missing (e.g. loaded draft edit items)
        if (item.stock === undefined || item.stock === null) {
            continue;
        }
        
        const stock = Number(item.stock) || 0;
        const packSize = Number(item.pack_size_ml) || 1;
        const looseSize = Number(item.loose_size_ml) || 1;
        const qty = Number(item.quantity) || 0;
        
        if (item.unitType === 'loose') {
            const looseQty = looseSize > 0 ? (stock / looseSize) : 0;
            if (qty > looseQty) {
                hasError = true;
                errorMsg = `Cannot save bill. "${item.name}" exceeds available loose stock (Available: ${looseQty.toFixed(1)} ${item.loose_unit || 'units'}).`;
                break;
            }
        } else {
            const packQty = packSize > 0 ? (stock / packSize) : 0;
            if (qty > packQty) {
                hasError = true;
                errorMsg = `Cannot save bill. "${item.name}" exceeds available stock (Available: ${packQty.toFixed(1)} ${item.unit || 'packs'}).`;
                break;
            }
        }
    }
    
    return { hasError, errorMsg };
}

async function saveAndProcessBill(shouldPrint) {
    if (Object.keys(billItems).length === 0) {
        statusMessage.textContent = "Please add items to the bill.";
        statusMessage.style.color = "red";
        setTimeout(() => (statusMessage.textContent = ''), 3000);
        return;
    }

    // Block saving if any items are out of stock or exceed stock limit
    const stockCheck = hasStockErrors();
    if (stockCheck.hasError) {
        statusMessage.textContent = stockCheck.errorMsg;
        statusMessage.style.color = "red";
        setTimeout(() => (statusMessage.textContent = ''), 5000);
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

    // 2. Prepare data for backend
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

    // 3. Send data to backend
    try {
        const resp = await fetch('/generate_bill', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(billData)
        });
        const result = await resp.json();

        if (resp.ok) {
            // Update printed bill number with the real DB bill ID
            document.getElementById('bill-no').textContent = result.bill_id;

            statusMessage.textContent = result.message || 'Bill generated.';
            statusMessage.style.color = 'green';

            if (shouldPrint) {
                isPrinting = true;
                // Open the print dialog now that the bill ID is set in DOM
                setTimeout(() => {
                    window.print();
                    isPrinting = false;
                }, 250);
            } else {
                resetBillUI();
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

// --- Quantity Modal Control Logic ---
function openQtyModal(item) {
    currentModalItem = item;
    
    modalMedName.textContent = item.name;
    modalMedCode.textContent = item.code ? `Code: ${item.code}` : 'Code: -';
    
    // Configure Unit Type dropdown
    modalUnitType.innerHTML = '';
    const packOpt = document.createElement('option');
    packOpt.value = 'pack';
    packOpt.textContent = `Pack (${item.unit || '-'}) — ₹${(Number(item.mrp) || 0).toFixed(2)}`;
    modalUnitType.appendChild(packOpt);
    
    if (item.loose_unit) {
        const looseOpt = document.createElement('option');
        looseOpt.value = 'loose';
        looseOpt.textContent = `Loose (${item.loose_unit}) — ₹${(Number(item.loose_mrp) || 0).toFixed(2)}`;
        modalUnitType.appendChild(looseOpt);
    }
    
    modalUnitType.value = 'pack';
    modalQty.value = 1;
    
    updateModalSubtotalAndStock();
    
    qtyModalOverlay.classList.add('active');
    setTimeout(() => {
        modalQty.focus();
        modalQty.select();
    }, 100);
}

function closeQtyModal() {
    qtyModalOverlay.classList.remove('active');
    currentModalItem = null;
    searchInput.focus();
}

function updateModalSubtotalAndStock() {
    if (!currentModalItem) return;
    
    const unitType = modalUnitType.value;
    const qty = parseFloat(modalQty.value) || 0;
    const price = unitType === 'loose' ? (Number(currentModalItem.loose_mrp) || 0) : (Number(currentModalItem.mrp) || 0);
    const subtotal = qty * price;
    
    modalSubtotal.textContent = `₹${subtotal.toFixed(2)}`;
    
    // Update stock banner details
    const stock = Number(currentModalItem.stock) || 0;
    const packSize = Number(currentModalItem.pack_size_ml) || 1;
    const looseSize = Number(currentModalItem.loose_size_ml) || 1;
    
    let displayStock = "";
    let isLow = false;
    let isOut = stock <= 0;
    
    if (unitType === 'pack') {
        const packs = packSize > 0 ? (stock / packSize) : 0;
        displayStock = `${packs.toFixed(1)} ${currentModalItem.unit || 'packs'}`;
        isLow = packs <= 5;
    } else {
        const units = looseSize > 0 ? (stock / looseSize) : 0;
        displayStock = `${units.toFixed(1)} ${currentModalItem.loose_unit || 'units'}`;
        isLow = units <= 50;
    }
    
    modalStockValue.textContent = displayStock;
    
    modalStockBanner.className = 'stock-display-banner';
    if (isOut) {
        modalStockBanner.classList.add('out');
        modalStockValue.textContent = `${displayStock} (Out of Stock)`;
    } else if (isLow) {
        modalStockBanner.classList.add('warn');
        modalStockValue.textContent = `${displayStock} (Low Stock)`;
    } else {
        modalStockBanner.classList.add('ok');
    }
}

function submitModalAdd() {
    if (!currentModalItem) return;
    
    const qty = parseInt(modalQty.value) || 1;
    const unitType = modalUnitType.value;
    
    addItemToBill(currentModalItem, qty, unitType);
    closeQtyModal();
}

// Modal event bindings
modalUnitType.addEventListener('change', updateModalSubtotalAndStock);
modalQty.addEventListener('input', updateModalSubtotalAndStock);

modalQty.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        submitModalAdd();
    } else if (e.key === 'Escape') {
        closeQtyModal();
    }
});

modalUnitType.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeQtyModal();
    }
});

modalCancelBtn.addEventListener('click', closeQtyModal);
modalAddBtn.addEventListener('click', submitModalAdd);

qtyModalOverlay.addEventListener('click', (e) => {
    if (e.target === qtyModalOverlay) {
        closeQtyModal();
    }
});

// --- Customer History Lookup by Phone ---
const fetchCustomerHistory = async () => {
    const phone = customerPhoneInput.value.trim();
    if (phone.length >= 10) {
        try {
            const response = await fetch(`/get_customer_history?phone=${encodeURIComponent(phone)}`);
            const data = await response.json();
            if (data.found) {
                customerHistoryInfo.innerHTML = `<strong>Last Visit:</strong> ${data.date} &nbsp;|&nbsp; <strong>Last Bill:</strong> ₹${data.total.toFixed(2)}`;
                customerHistoryInfo.style.display = 'inline-block';
            } else {
                customerHistoryInfo.style.display = 'none';
            }
        } catch (e) {
            console.error("Error fetching customer history:", e);
            customerHistoryInfo.style.display = 'none';
        }
    } else {
        customerHistoryInfo.style.display = 'none';
    }
};

customerPhoneInput.addEventListener('input', debounce(fetchCustomerHistory, 300));
customerPhoneInput.addEventListener('change', fetchCustomerHistory);

// --- Global Event Listeners for Persistence ---

window.addEventListener('beforeunload', (e) => {
    if (isPrinting) {
        return;
    }

    if (Object.keys(billItems).length > 0) {
        saveBillToSession();
    } else {
        clearBillSession();
    }
});

window.addEventListener('focus', () => {
    if (isPrinting) {
        isPrinting = false;
        clearBillSession();
        window.location.reload();
    }
});

// Dynamic footer colspan adjustments for print vs screen layout
window.addEventListener('beforeprint', () => {
    document.querySelectorAll('#bill-table tfoot td[colspan="6"]').forEach(td => {
        td.setAttribute('colspan', '5');
    });
});

window.addEventListener('afterprint', () => {
    document.querySelectorAll('#bill-table tfoot td[colspan="5"]').forEach(td => {
        td.setAttribute('colspan', '6');
    });
});

document.addEventListener('DOMContentLoaded', () => {
    if (Object.keys(billItems).length === 0) {
        loadBillFromSession();
    }
});