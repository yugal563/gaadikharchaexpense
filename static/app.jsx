const { useState, useEffect, useRef } = React;

function App() {
    const [expenses, setExpenses] = useState([]);
    const [loading, setLoading] = useState(true);
    const [categoryFilter, setCategoryFilter] = useState("");
    const [availableCategories, setAvailableCategories] = useState(["Fuel", "Maintenance", "Vehicle", "Other"]);
    const [searchQuery, setSearchQuery] = useState("");
    const [activeTab, setActiveTab] = useState("all"); // 'all', 'paid', 'unpaid'
    const [selectedExpense, setSelectedExpense] = useState(null); // for details modal
    const [showAdvanced, setShowAdvanced] = useState(false);

    // ── Receipt Scanner State ──────────────────
    const [leftPanelMode, setLeftPanelMode] = useState("manual"); // 'manual' | 'scanner'
    const [scanFiles, setScanFiles] = useState([]);
    const [scanPreviews, setScanPreviews] = useState([]);
    const [scanLoading, setScanLoading] = useState(false);
    const [scanStep, setScanStep] = useState(""); // status message
    const [scanResult, setScanResult] = useState(null); // parsed result from API
    const [isDragOver, setIsDragOver] = useState(false);
    const fileInputRef = useRef(null);
    const [scanVerifyData, setScanVerifyData] = useState(null); // pre-filled editable data

    // Form State
    const initialFormState = {
        category: "Fuel",
        vehicle: "",
        vehicle_record_type: "general",
        expense_date: new Date().toISOString().split('T')[0],
        parking_location: "",
        petrol_pump: "",
        location: "",
        liters: "",
        rate_per_liter: "",
        odometer: "",
        service_type: "",
        vendor: "",
        remark: "",
        amount: "",
        paid: true,
        registration_no: "",
        challan_no: "",
        challan_type: "",
        violation_type: "",
        issued_by: "",
        due_date: "",
        remarks: "",
        party_type: "",
        party: "",
        expense_name: "",
        vendor_type: "",
        maintenance_item: "",
        custom_maintenance_item: "",
        invoice_number: "",
        taxable_amount: "",
        non_taxable_amount: "",
        km_limit: "",
        hour_limit: "",
        excess_km_rate: "",
        excess_hour_rate: "",
        excess_km_amount: "",
        excess_hour_amount: "",
        driver_allowance: "",
        toll_charges: "",
        parking_charges: "",
        other_charges: "",
        tds_percentage: "",
        tds_amount: "",
        gst_percentage: "",
        gst_amount: "",
        gst_invoicing_type: "",
        gst_applicable_on_parking: false,
        gst_applicable_on_toll: false,
        gst_applicable_on_other_charges: false,
        paid_to: "",
        contact_number: ""
    };
    const [form, setForm] = useState(initialFormState);
    const [notification, setNotification] = useState(null);

    const showToast = (message, type = "success") => {
        setNotification({ message, type });
        setTimeout(() => setNotification(null), 4000);
    };

    const fetchExpenses = async () => {
        setLoading(true);
        try {
            // Using relative URL so it auto-targets the active backend host/port
            const url = categoryFilter
                ? `/expenses/category/${categoryFilter}`
                : `/expenses`;
            const res = await fetch(url);
            if (!res.ok) throw new Error("Failed to fetch expenses");
            const data = await res.json();
            setExpenses(data);

            if (!categoryFilter) {
                const uniqueCats = Array.from(new Set(data.map(item => item.category).filter(Boolean)));
                const mergedCats = Array.from(new Set(["Fuel", "Maintenance", "Vehicle", "Other", ...uniqueCats]));
                setAvailableCategories(mergedCats);
            }
        } catch (err) {
            showToast(err.message, "error");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchExpenses();
    }, [categoryFilter]);

    const handleInputChange = (e) => {
        const { name, value, type, checked } = e.target;
        setForm(prev => ({
            ...prev,
            [name]: type === 'checkbox' ? checked : value
        }));
    };

    const formatDate = (value, options = { day: '2-digit', month: 'short', year: 'numeric' }) => {
        if (!value) return "N/A";
        const parsed = new Date(value);
        return Number.isNaN(parsed.getTime())
            ? value
            : parsed.toLocaleDateString("en-IN", options);
    };

    const isChallanExpense = (expense) => {
        if (!expense || expense.category !== "Vehicle") return false;
        return Boolean(
            expense.challan_no ||
            expense.challan_type ||
            expense.violation_type ||
            expense.issued_by ||
            expense.due_date
        );
    };

    const getRecordTitle = (expense) => {
        if (isChallanExpense(expense)) {
            return expense.challan_no || expense.vehicle || "Vehicle Record";
        }
        if (expense.category === "Vehicle" && expense.service_type === "parking") {
            return expense.location || expense.vehicle || "Parking Record";
        }
        return expense.vehicle || expense.vendor || "General Expense";
    };

    // Auto calculate amount if liters and rate are filled
    useEffect(() => {
        if (form.category === "Fuel" && form.liters && form.rate_per_liter) {
            const calculated = parseFloat(form.liters) * parseFloat(form.rate_per_liter);
            if (!isNaN(calculated)) {
                setForm(prev => ({ ...prev, amount: calculated.toFixed(2) }));
            }
        }
    }, [form.liters, form.rate_per_liter, form.category]);

    const handleSubmit = async (e) => {
        e.preventDefault();

        const isFuel = form.category === "Fuel";
        const isMaintenance = form.category === "Maintenance";
        const isVehicle = form.category === "Vehicle";
        const isParking = isVehicle && form.vehicle_record_type === "parking";
        const isVehicleChallan = isVehicle && form.vehicle_record_type === "challan";
        const isVehicleOther = isVehicle && form.vehicle_record_type === "other";
        const amountValue = form.amount;

        if (!form.category || amountValue === "" || !form.expense_date) {
            showToast("Please fill in Category, Amount, and Date.", "error");
            return;
        }

        const parsedAmount = parseFloat(amountValue);
        if (isNaN(parsedAmount)) {
            showToast("Please enter a valid numeric amount.", "error");
            return;
        }

        const { vehicle_record_type, ...formValues } = form;

        const payload = {
            ...formValues,
            amount: parsedAmount,
            liters: isFuel && form.liters ? parseFloat(form.liters) : null,
            rate_per_liter: isFuel && form.rate_per_liter ? parseFloat(form.rate_per_liter) : null,
            odometer: form.odometer ? parseInt(form.odometer, 10) : null,
            vehicle: form.vehicle || null,
            petrol_pump: isFuel ? form.petrol_pump || null : null,
            location: form.location || null,
            service_type: isMaintenance ? form.service_type || null : (isVehicle && !['general', 'challan'].includes(form.vehicle_record_type) ? form.vehicle_record_type : null),
            vendor: isMaintenance ? form.vendor || null : null,
            remarks: form.remarks || form.remark || null,
            registration_no: form.registration_no || null,
            challan_no: isVehicleChallan ? form.challan_no || null : null,
            challan_type: isVehicleChallan ? form.challan_type || null : null,
            violation_type: isVehicleChallan ? form.violation_type || null : null,
            issued_by: isVehicleChallan ? form.issued_by || null : null,
            due_date: isVehicleChallan ? form.due_date || null : null,
            party_type: isVehicleOther || form.category === "Other" ? form.party_type || null : null,
            party: isVehicleOther || form.category === "Other" ? form.party || null : null,
            expense_name: isVehicleOther || form.category === "Other" ? form.expense_name || null : null,
            contact_number: form.contact_number || null,
            
            // Explicitly map some new fields that need float/int parsing (or rely on Pydantic)
            taxable_amount: form.taxable_amount ? parseFloat(form.taxable_amount) : null,
            gst_amount: form.gst_amount ? parseFloat(form.gst_amount) : null,
        };

        try {
            const res = await fetch("/expenses", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => null);
                const errMsg = errData?.detail
                    ? (typeof errData.detail === 'string' ? errData.detail : errData.detail[0]?.msg)
                    : "Failed to save expense";
                throw new Error(`API Error: ${errMsg}`);
            }

            showToast("Expense added successfully!", "success");
            setForm(initialFormState);
            setShowAdvanced(false);
            fetchExpenses();
        } catch (err) {
            showToast(err.message, "error");
        }
    };

    // ── Receipt Scanner Handlers ───────────────
    const handleFileSelect = (files) => {
        let validFiles = Array.from(files).filter(f => f.type.startsWith("image/") || f.type === "application/pdf");
        
        // De-duplicate files by size (bytes) and clean names to prevent OS/Clipboard duplicates
        const seenSizes = new Set();
        const seenNames = new Set();
        validFiles = validFiles.filter(file => {
            const cleanName = file.name.replace(/\.[^/.]+$/, "").replace(/\s*\(\d+\)\s*$/, "").trim().toLowerCase();
            if (seenSizes.has(file.size) || (cleanName && seenNames.has(cleanName))) {
                return false;
            }
            if (file.size) seenSizes.add(file.size);
            if (cleanName) seenNames.add(cleanName);
            return true;
        });

        if (validFiles.length === 0) {
            showToast("Please select valid image or PDF files.", "error");
            return;
        }
        setScanFiles(validFiles);
        setScanResult(null);
        setScanStep("");
        
        const previews = [];
        validFiles.forEach((file, index) => {
            const reader = new FileReader();
            reader.onload = (e) => {
                previews[index] = e.target.result;
                if (previews.filter(Boolean).length === validFiles.length) {
                    setScanPreviews([...previews]);
                }
            };
            reader.readAsDataURL(file);
        });
    };

    const handleDrop = (e) => {
        e.preventDefault();
        setIsDragOver(false);
        handleFileSelect(e.dataTransfer.files);
    };

    const compressImage = (file, maxDim = 1600, quality = 0.85) => {
        return new Promise((resolve) => {
            if (file.type === "application/pdf") {
                resolve(file);
                return;
            }

            const reader = new FileReader();
            reader.onload = (e) => {
                const img = new Image();
                img.onload = () => {
                    const canvas = document.createElement("canvas");
                    let width = img.width;
                    let height = img.height;

                    if (width > maxDim || height > maxDim) {
                        if (width > height) {
                            height = Math.round((height * maxDim) / width);
                            width = maxDim;
                        } else {
                            width = Math.round((width * maxDim) / height);
                            height = maxDim;
                        }
                    }

                    canvas.width = width;
                    canvas.height = height;
                    const ctx = canvas.getContext("2d");
                    ctx.drawImage(img, 0, 0, width, height);

                    canvas.toBlob(
                        (blob) => {
                            const compressedFile = new File([blob], file.name.replace(/\.[^/.]+$/, "") + ".jpg", {
                                type: "image/jpeg",
                                lastModified: Date.now(),
                            });
                            resolve(compressedFile);
                        },
                        "image/jpeg",
                        quality
                    );
                };
                img.onerror = () => resolve(file);
                img.src = e.target.result;
            };
            reader.onerror = () => resolve(file);
            reader.readAsDataURL(file);
        });
    };

    const handleScanSubmit = async () => {
        if (scanFiles.length === 0) { showToast("Please select at least one receipt file.", "error"); return; }
        setScanLoading(true);
        setScanResult(null);
        try {
            setScanStep("Preparing & compressing images...");
            const compressedFiles = await Promise.all(scanFiles.map(file => compressImage(file, 1600, 0.85)));

            setScanStep("Uploading files...");
            const formData = new FormData();
            compressedFiles.forEach(file => formData.append("files", file));

            setScanStep("Analyzing receipts visually with multimodal AI...");
            const res = await fetch("/scan-receipt", { method: "POST", body: formData });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || "Scan failed");
            }

            setScanStep("Parsing and categorising...");
            const data = await res.json();
            setScanResult(data);
            setScanStep("Done!");
            showToast(data.message || "Receipts scanned & saved successfully! 🎉", "success");
            fetchExpenses();
        } catch (err) {
            showToast(err.message, "error");
            setScanStep("");
        } finally {
            setScanLoading(false);
        }
    };

    const resetScanner = () => {
        setScanFiles([]);
        setScanPreviews([]);
        setScanResult(null);
        setScanVerifyData(null);
        setScanStep("");
        setScanLoading(false);
        if (fileInputRef.current) fileInputRef.current.value = "";
    };

    // ── Scan & Verify (no DB write yet) ───────────
    const handleScanVerify = async () => {
        if (scanFiles.length === 0) { showToast("Please select at least one receipt file.", "error"); return; }
        setScanLoading(true);
        setScanResult(null);
        setScanVerifyData(null);
        try {
            setScanStep("Preparing & compressing images...");
            const compressedFiles = await Promise.all(scanFiles.map(file => compressImage(file, 1600, 0.85)));

            setScanStep("Analyzing receipts visually with multimodal AI...");
            const formData = new FormData();
            compressedFiles.forEach(file => formData.append("files", file));
            const res = await fetch("/scan-receipt-debug", { method: "POST", body: formData });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || "Scan failed");
            }
            const data = await res.json();
            setScanVerifyData(data.receipts || []);
            setScanStep("");
            showToast("Receipts scanned! Please verify the details below.", "success");
        } catch (err) {
            showToast(err.message, "error");
            setScanStep("");
        } finally {
            setScanLoading(false);
        }
    };

    // ── Confirm & Save after verification ─────────
    const handleConfirmAndSave = async () => {
        if (!scanVerifyData || scanVerifyData.length === 0) return;
        try {
            for (const data of scanVerifyData) {
                const payload = {
                    category:        data.category || "Other",
                    expense_date:    data.expense_date,
                    amount:          parseFloat(data.amount) || 0,
                    liters:          data.liters          ? parseFloat(data.liters)          : null,
                    rate_per_liter:  data.rate_per_liter  ? parseFloat(data.rate_per_liter)  : null,
                    odometer:        data.odometer        ? parseInt(data.odometer, 10)      : null,
                    petrol_pump:     data.petrol_pump     || null,
                    vendor:          data.vendor          || null,
                    registration_no: data.registration_no || null,
                    location:        data.location        || null,
                    service_type:    data.service_type    || null,
                    remarks:         data.remarks         || null,
                    paid:            true,
                    
                    // New DB columns
                    vendor_type: data.vendor_type || null,
                    parking_location: data.parking_location || null,
                    maintenance_item: data.maintenance_item || null,
                    custom_maintenance_item: data.custom_maintenance_item || null,
                    invoice_number: data.invoice_number || null,
                    taxable_amount: data.taxable_amount ? parseFloat(data.taxable_amount) : null,
                    non_taxable_amount: data.non_taxable_amount ? parseFloat(data.non_taxable_amount) : null,
                    km_limit: data.km_limit ? parseInt(data.km_limit, 10) : null,
                    hour_limit: data.hour_limit ? parseInt(data.hour_limit, 10) : null,
                    excess_km_rate: data.excess_km_rate ? parseFloat(data.excess_km_rate) : null,
                    excess_hour_rate: data.excess_hour_rate ? parseFloat(data.excess_hour_rate) : null,
                    excess_km_amount: data.excess_km_amount ? parseFloat(data.excess_km_amount) : null,
                    excess_hour_amount: data.excess_hour_amount ? parseFloat(data.excess_hour_amount) : null,
                    driver_allowance: data.driver_allowance ? parseFloat(data.driver_allowance) : null,
                    toll_charges: data.toll_charges ? parseFloat(data.toll_charges) : null,
                    parking_charges: data.parking_charges ? parseFloat(data.parking_charges) : null,
                    other_charges: data.other_charges ? parseFloat(data.other_charges) : null,
                    tds_percentage: data.tds_percentage ? parseFloat(data.tds_percentage) : null,
                    tds_amount: data.tds_amount ? parseFloat(data.tds_amount) : null,
                    gst_percentage: data.gst_percentage ? parseFloat(data.gst_percentage) : null,
                    gst_amount: data.gst_amount ? parseFloat(data.gst_amount) : null,
                    gst_invoicing_type: data.gst_invoicing_type || null,
                    gst_applicable_on_parking: Boolean(data.gst_applicable_on_parking),
                    gst_applicable_on_toll: Boolean(data.gst_applicable_on_toll),
                    gst_applicable_on_other_charges: Boolean(data.gst_applicable_on_other_charges),
                    paid_to: data.paid_to || null,
                    contact_number: data.contact_number || null,
                };

                // Copy over any custom fields not present in standard payload
                const standardKeys = [
                    "category", "expense_date", "amount", "liters", "rate_per_liter", "odometer",
                    "petrol_pump", "vendor", "registration_no", "location", "service_type", "remarks",
                    "paid", "vendor_type", "parking_location", "maintenance_item", "custom_maintenance_item",
                    "invoice_number", "taxable_amount", "non_taxable_amount", "km_limit", "hour_limit",
                    "excess_km_rate", "excess_hour_rate", "excess_km_amount", "excess_hour_amount",
                    "driver_allowance", "toll_charges", "parking_charges", "other_charges", "tds_percentage",
                    "tds_amount", "gst_percentage", "gst_amount", "gst_invoicing_type", "gst_applicable_on_parking",
                    "gst_applicable_on_toll", "gst_applicable_on_other_charges", "paid_to", "contact_number"
                ];
                for (const key in data) {
                    if (!standardKeys.includes(key) && data[key] !== undefined && data[key] !== null) {
                        payload[key] = data[key];
                    }
                }

                const res = await fetch("/expenses", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                if (!res.ok) {
                    const err = await res.json().catch(() => ({}));
                    throw new Error(err.detail || "Failed to save expense");
                }
            }
            showToast("All expenses verified & saved successfully! 🎉", "success");
            resetScanner();
            fetchExpenses();
        } catch (err) {
            showToast(err.message, "error");
        }
    };

    const handleDelete = async (id, e) => {
        e.stopPropagation(); // Prevent opening detail modal
        if (!confirm("Are you sure you want to delete this expense?")) return;

        try {
            const res = await fetch(`/expenses/${id}`, {
                method: "DELETE"
            });
            if (!res.ok) throw new Error("Failed to delete expense");

            showToast("Expense deleted successfully", "success");
            if (selectedExpense && selectedExpense.expense_id === id) {
                setSelectedExpense(null);
            }
            fetchExpenses();
        } catch (err) {
            showToast(err.message, "error");
        }
    };

    // Calculate Statistics
    const totalExpenses = expenses.reduce((sum, item) => sum + (Number(item.amount) || 0), 0);
    const fuelExpenses = expenses.filter(item => item.category === "Fuel").reduce((sum, item) => sum + (Number(item.amount) || 0), 0);
    const maintenanceExpenses = expenses.filter(item => item.category === "Maintenance").reduce((sum, item) => sum + (Number(item.amount) || 0), 0);
    const pendingExpenses = expenses.filter(item => !item.paid).reduce((sum, item) => sum + (Number(item.amount) || 0), 0);

    // Apply Filters (Search and Tab)
    const filteredExpenses = expenses.filter(item => {
        const normalizedQuery = searchQuery.trim().toLowerCase();
        const matchesSearch =
            !normalizedQuery ||
            (item.vehicle && item.vehicle.toLowerCase().includes(normalizedQuery)) ||
            (item.category && item.category.toLowerCase().includes(normalizedQuery)) ||
            (item.remark && item.remark.toLowerCase().includes(normalizedQuery)) ||
            (item.location && item.location.toLowerCase().includes(normalizedQuery)) ||
            (item.vendor && item.vendor.toLowerCase().includes(normalizedQuery)) ||
            (item.challan_no && item.challan_no.toLowerCase().includes(normalizedQuery)) ||
            (item.challan_type && item.challan_type.toLowerCase().includes(normalizedQuery)) ||
            (item.violation_type && item.violation_type.toLowerCase().includes(normalizedQuery)) ||
            (item.issued_by && item.issued_by.toLowerCase().includes(normalizedQuery)) ||
            (item.remarks && item.remarks.toLowerCase().includes(normalizedQuery));

        const matchesTab =
            activeTab === "all" ||
            (activeTab === "paid" && item.paid) ||
            (activeTab === "unpaid" && !item.paid);

        return matchesSearch && matchesTab;
    });

    return (
        <div className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
            {/* Header */}
            <div className="flex flex-col md:flex-row md:items-center md:justify-between pb-8 border-b border-slate-800 mb-8">
                <div>
                    <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
                        <i className="fa-solid fa-gauge-high mr-3 text-indigo-400"></i>
                        Expense Tracker
                    </h1>
                    <p className="mt-2 text-sm text-slate-400">
                        Manage fuel logs, maintenance receipts, and overall vehicle running costs in real-time.
                    </p>
                </div>
                <div className="mt-4 md:mt-0 flex items-center gap-3">
                    <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        <span className="w-2 h-2 mr-2 bg-emerald-400 rounded-full animate-pulse"></span>
                        Connected to DB
                    </span>
                </div>
            </div>

            {/* Notification Toast */}
            {notification && (
                <div className={`fixed top-5 right-5 z-50 flex items-center p-4 rounded-xl shadow-2xl border transition-all duration-300 ${notification.type === "error"
                    ? "bg-rose-950/80 border-rose-800 text-rose-200"
                    : "bg-emerald-950/80 border-emerald-800 text-emerald-200"
                    } backdrop-blur-md`}>
                    <i className={`fa-solid ${notification.type === "error" ? "fa-circle-xmark text-rose-400" : "fa-circle-check text-emerald-400"} mr-3 text-lg`}></i>
                    <span className="font-medium text-sm">{notification.message}</span>
                </div>
            )}

            {/* Stat Widgets */}
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4 mb-8">
                {/* Total Exp */}
                <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 hover:border-slate-700 transition-all duration-300 relative overflow-hidden group">
                    <div className="absolute -right-4 -bottom-4 text-6xl text-slate-800/20 group-hover:scale-110 transition-transform duration-300">
                        <i className="fa-solid fa-wallet"></i>
                    </div>
                    <p className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Total Expenses</p>
                    <p className="mt-2 text-3xl font-extrabold text-white">₹{totalExpenses.toLocaleString("en-IN")}</p>
                    <p className="mt-1 text-xs text-indigo-400 flex items-center">
                        <i className="fa-solid fa-arrow-trend-up mr-1"></i> Cumulative logs
                    </p>
                </div>

                {/* Fuel Expenses */}
                <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 hover:border-slate-700 transition-all duration-300 relative overflow-hidden group">
                    <div className="absolute -right-4 -bottom-4 text-6xl text-slate-800/20 group-hover:scale-110 transition-transform duration-300">
                        <i className="fa-solid fa-gas-pump"></i>
                    </div>
                    <p className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Fuel Spend</p>
                    <p className="mt-2 text-3xl font-extrabold text-cyan-400">₹{fuelExpenses.toLocaleString("en-IN")}</p>
                    <p className="mt-1 text-xs text-slate-500">
                        {expenses.filter(i => i.category === "Fuel").length} refuel entries
                    </p>
                </div>

                {/* Maintenance Spend */}
                <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 hover:border-slate-700 transition-all duration-300 relative overflow-hidden group">
                    <div className="absolute -right-4 -bottom-4 text-6xl text-slate-800/20 group-hover:scale-110 transition-transform duration-300">
                        <i className="fa-solid fa-wrench"></i>
                    </div>
                    <p className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Maintenance</p>
                    <p className="mt-2 text-3xl font-extrabold text-purple-400">₹{maintenanceExpenses.toLocaleString("en-IN")}</p>
                    <p className="mt-1 text-xs text-slate-500">
                        {expenses.filter(i => i.category === "Maintenance").length} service logs
                    </p>
                </div>

                {/* Unpaid Bills */}
                <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 hover:border-slate-700 transition-all duration-300 relative overflow-hidden group">
                    <div className="absolute -right-4 -bottom-4 text-6xl text-slate-800/20 group-hover:scale-110 transition-transform duration-300">
                        <i className="fa-solid fa-clock"></i>
                    </div>
                    <p className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Pending Bills</p>
                    <p className="mt-2 text-3xl font-extrabold text-amber-400">₹{pendingExpenses.toLocaleString("en-IN")}</p>
                    <p className="mt-1 text-xs text-amber-500/80 flex items-center">
                        <i className="fa-solid fa-circle-exclamation mr-1 animate-pulse"></i> Needs payment
                    </p>
                </div>
            </div>

            {/* Dashboard Content */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">

                {/* Left Side: Add Expense Form / Scanner (lg:col-span-4) */}
                <div className="lg:col-span-4">
                    <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-6 sticky top-8">

                        {/* Mode Toggle */}
                        <div className="flex rounded-xl overflow-hidden border border-slate-700 mb-6">
                            <button
                                type="button"
                                onClick={() => { setLeftPanelMode("manual"); resetScanner(); }}
                                className={`flex-1 flex items-center justify-center gap-2 py-2.5 text-xs font-bold uppercase tracking-wider transition-all ${
                                    leftPanelMode === "manual"
                                        ? "bg-indigo-600 text-white shadow-lg"
                                        : "text-slate-400 hover:text-white hover:bg-slate-800"
                                }`}
                            >
                                <i className="fa-solid fa-pen-to-square"></i> Manual Entry
                            </button>
                            <button
                                type="button"
                                onClick={() => setLeftPanelMode("scanner")}
                                className={`flex-1 flex items-center justify-center gap-2 py-2.5 text-xs font-bold uppercase tracking-wider transition-all ${
                                    leftPanelMode === "scanner"
                                        ? "bg-violet-600 text-white shadow-lg"
                                        : "text-slate-400 hover:text-white hover:bg-slate-800"
                                }`}
                            >
                                <i className="fa-solid fa-camera"></i> Scan Receipt
                            </button>
                        </div>

                        {/* ── RECEIPT SCANNER PANEL ──────────────────── */}
                        {leftPanelMode === "scanner" && (
                            <div className="space-y-4">
                                <div>
                                    <p className="text-sm font-semibold text-violet-300 flex items-center gap-2 mb-1">
                                        <i className="fa-solid fa-wand-magic-sparkles"></i>
                                        AI Receipt Scanner
                                    </p>
                                    <p className="text-xs text-slate-500">Upload a photo of any receipt. Multimodal AI will visually extract data and auto-save it.</p>
                                </div>

                                {/* Drop Zone */}
                                {scanFiles.length === 0 ? (
                                    <div
                                        onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
                                        onDragLeave={() => setIsDragOver(false)}
                                        onDrop={handleDrop}
                                        onClick={() => fileInputRef.current?.click()}
                                        className={`relative flex flex-col items-center justify-center gap-3 p-8 rounded-2xl border-2 border-dashed cursor-pointer transition-all duration-300 ${
                                            isDragOver
                                                ? "border-violet-500 bg-violet-500/10 scale-[1.02]"
                                                : "border-slate-700 hover:border-violet-600 hover:bg-violet-500/5"
                                        }`}
                                    >
                                        <div className={`w-14 h-14 rounded-2xl flex items-center justify-center text-2xl transition-all duration-300 ${
                                            isDragOver ? "bg-violet-500/20 text-violet-400" : "bg-slate-800 text-slate-500"
                                        }`}>
                                            <i className="fa-solid fa-cloud-arrow-up"></i>
                                        </div>
                                        <div className="text-center">
                                            <p className="text-sm font-semibold text-slate-300">Drop receipts here</p>
                                            <p className="text-xs text-slate-500 mt-0.5">or click to browse multiple files</p>
                                        </div>
                                        <p className="text-[10px] text-slate-600">JPEG · PNG · BMP · TIFF · WebP · PDF</p>
                                        <input
                                            ref={fileInputRef}
                                            type="file"
                                            multiple
                                            accept="image/*,application/pdf"
                                            className="hidden"
                                            onChange={(e) => handleFileSelect(e.target.files)}
                                        />
                                    </div>
                                ) : (
                                    <div className="space-y-3">
                                        {/* Grid of Previews */}
                                        <div className="grid grid-cols-2 gap-3 max-h-64 overflow-y-auto pr-1">
                                            {scanFiles.map((file, idx) => (
                                                <div key={idx} className="relative rounded-xl overflow-hidden border border-slate-700 bg-slate-950 flex flex-col items-center justify-center p-3 h-32 group">
                                                    {file.type === "application/pdf" ? (
                                                        <div className="flex flex-col items-center justify-center text-slate-400">
                                                            <i className="fa-solid fa-file-pdf text-3xl text-rose-500 mb-2"></i>
                                                            <p className="text-[10px] text-slate-400 truncate w-[100px] text-center">{file.name}</p>
                                                        </div>
                                                    ) : (
                                                        <img
                                                            src={scanPreviews[idx]}
                                                            alt={`Preview ${idx}`}
                                                            className="w-full h-full object-cover rounded-lg opacity-80 group-hover:opacity-100 transition-opacity"
                                                        />
                                                    )}
                                                </div>
                                            ))}
                                        </div>
                                        
                                        {!scanLoading && !scanResult && (
                                            <div className="flex justify-between items-center px-1">
                                                <span className="text-xs text-slate-400 font-medium">{scanFiles.length} file(s) ready</span>
                                                <button onClick={resetScanner} className="text-xs text-rose-400 hover:text-rose-300 font-medium px-3 py-1 rounded bg-rose-500/10">
                                                    Clear All
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* Processing Steps */}
                                {scanLoading && (
                                    <div className="bg-violet-950/30 border border-violet-800/30 rounded-xl p-4 space-y-3">
                                        <div className="flex items-center gap-3">
                                            <div className="w-8 h-8 rounded-full bg-violet-500/20 flex items-center justify-center">
                                                <i className="fa-solid fa-circle-notch fa-spin text-violet-400"></i>
                                            </div>
                                            <div>
                                                <p className="text-xs font-bold text-violet-300">Processing {scanFiles.length} Receipt{scanFiles.length > 1 ? 's' : ''}</p>
                                                <p className="text-[11px] text-slate-400 mt-0.5">{scanStep}</p>
                                            </div>
                                        </div>
                                        {/* Animated pipeline steps */}
                                        <div className="space-y-1.5 pl-2">
                                            {[
                                                { label: "Upload Files", icon: "fa-cloud-arrow-up" },
                                                { label: "Multimodal AI Visual Scanning", icon: "fa-eye" },
                                                { label: "Categorise & Parse Fields", icon: "fa-tags" },
                                                { label: "Save to MySQL Database", icon: "fa-database" },
                                            ].map((step, i) => (
                                                <div key={i} className="flex items-center gap-2">
                                                    <div className="w-5 h-5 rounded-full bg-violet-900/60 flex items-center justify-center">
                                                        <i className={`fa-solid ${step.icon} text-[9px] text-violet-400`}></i>
                                                    </div>
                                                    <span className="text-[11px] text-slate-400">{step.label}</span>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* Result Card */}
                                {scanResult && !scanLoading && (
                                    <div className="bg-emerald-950/30 border border-emerald-800/40 rounded-xl p-4 space-y-3">
                                        <div className="flex items-center justify-between">
                                            <p className="text-xs font-bold text-emerald-400 flex items-center gap-2">
                                                <i className="fa-solid fa-circle-check"></i>
                                                Saved as Expense #{scanResult.expense_id}
                                            </p>
                                            <button onClick={resetScanner} className="text-[10px] text-slate-400 hover:text-white underline">Scan Another</button>
                                        </div>

                                        {scanResult.extracted?.filename && (
                                            <div className="text-[10px] text-slate-400 font-mono bg-slate-950/40 px-2.5 py-1.5 rounded-lg border border-slate-800/60 truncate">
                                                Source File: {scanResult.extracted.filename}
                                            </div>
                                        )}

                                        <div className="grid grid-cols-2 gap-2">
                                             {(() => {
                                                 const cat = scanResult.extracted?.category || "Other";
                                                 const ext = scanResult.extracted || {};
                                                 
                                                 const fields = [
                                                     { label: "Category", value: ext.category, icon: "fa-tag" },
                                                     { label: "Amount", value: ext.amount ? `₹${Number(ext.amount).toLocaleString('en-IN')}` : "N/A", icon: "fa-indian-rupee-sign" },
                                                     { label: "Date", value: ext.expense_date, icon: "fa-calendar" },
                                                 ];

                                                 if (cat === "Fuel") {
                                                     fields.push(
                                                         { label: "Petrol Pump", value: ext.petrol_pump || ext.vendor || "—", icon: "fa-gas-pump" },
                                                         { label: "Liters", value: ext.liters ? `${ext.liters} L` : "—", icon: "fa-droplet" },
                                                         { label: "Rate/L", value: ext.rate_per_liter ? `₹${ext.rate_per_liter}` : "—", icon: "fa-coins" }
                                                     );
                                                 } else if (cat === "Maintenance") {
                                                     fields.push(
                                                         { label: "Workshop", value: ext.vendor || "—", icon: "fa-store" },
                                                         { label: "Service Type", value: ext.service_type || "—", icon: "fa-screwdriver-wrench" },
                                                         { label: "Odometer", value: ext.odometer ? `${ext.odometer.toLocaleString()} km` : "—", icon: "fa-gauge" }
                                                     );
                                                 } else if (cat === "Vehicle") {
                                                     const isChallan = ext.challan_no || ext.challan_type || ext.issued_by;
                                                     if (isChallan) {
                                                         fields.push(
                                                             { label: "Challan No", value: ext.challan_no || "—", icon: "fa-file-invoice" },
                                                             { label: "Violation", value: ext.violation_type || "—", icon: "fa-triangle-exclamation" },
                                                             { label: "Issued By", value: ext.issued_by || "—", icon: "fa-building-shield" }
                                                         );
                                                     } else {
                                                         fields.push(
                                                             { label: "Location", value: ext.location || ext.parking_location || "—", icon: "fa-location-dot" },
                                                             { label: "Service Type", value: ext.service_type || ext.challan_type || "—", icon: "fa-circle-info" },
                                                             { label: "Payment Mode", value: ext.payment_mode || "—", icon: "fa-credit-card" }
                                                         );
                                                     }
                                                 } else {
                                                     fields.push(
                                                         { label: "Party/Vendor", value: ext.party || ext.vendor || "—", icon: "fa-store" },
                                                         { label: "Expense Name", value: ext.expense_name || "—", icon: "fa-signature" },
                                                         { label: "Payment Mode", value: ext.payment_mode || "—", icon: "fa-credit-card" }
                                                     );
                                                 }

                                                 return fields.map(({ label, value, icon }) => (
                                                     <div key={label} className="bg-slate-900/60 rounded-lg p-2.5">
                                                         <p className="text-[10px] text-slate-500 flex items-center gap-1">
                                                             <i className={`fa-solid ${icon}`}></i> {label}
                                                         </p>
                                                         <p className="text-xs font-bold text-white mt-0.5 truncate" title={value}>{value}</p>
                                                     </div>
                                                 ));
                                             })()}
                                         </div>

                                        {/* Raw OCR text expandable */}
                                        <details className="group">
                                            <summary className="text-[10px] text-slate-500 cursor-pointer hover:text-slate-300 list-none flex items-center gap-1">
                                                <i className="fa-solid fa-chevron-right group-open:rotate-90 transition-transform text-[8px]"></i>
                                                View raw OCR text
                                            </summary>
                                            <pre className="mt-2 text-[10px] text-slate-400 bg-slate-950 p-2 rounded-lg max-h-28 overflow-y-auto whitespace-pre-wrap leading-relaxed">{scanResult.extracted?.raw_text}</pre>
                                        </details>
                                    </div>
                                )}

                                {/* Scan Buttons — shown when image selected but not yet saved */}
                                {scanFiles.length > 0 && !scanResult && !scanVerifyData && (
                                    <div className="grid grid-cols-2 gap-2">
                                        {/* Auto-Save */}
                                        <button
                                            onClick={handleScanSubmit}
                                            disabled={scanLoading}
                                            id="scan-receipt-btn"
                                            className="py-3 flex items-center justify-center gap-2 bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-xl shadow-lg shadow-violet-600/20 transition-all duration-300 text-xs"
                                        >
                                            {scanLoading ? (
                                                <><i className="fa-solid fa-circle-notch fa-spin"></i> Scanning...</>
                                            ) : (
                                                <><i className="fa-solid fa-bolt"></i> Auto-Save</>
                                            )}
                                        </button>
                                        {/* Verify First */}
                                        <button
                                            onClick={handleScanVerify}
                                            disabled={scanLoading}
                                            id="scan-verify-btn"
                                            className="py-3 flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 border border-slate-600 hover:border-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-bold rounded-xl transition-all duration-300 text-xs"
                                        >
                                            {scanLoading ? (
                                                <><i className="fa-solid fa-circle-notch fa-spin"></i> Scanning...</>
                                            ) : (
                                                <><i className="fa-solid fa-eye"></i> Verify First</>
                                            )}
                                        </button>
                                    </div>
                                )}

                                {/* ── Verification / Edit Form ─────────────── */}
                                {scanVerifyData && scanVerifyData.length > 0 && (
                                    <div className="bg-amber-950/10 rounded-xl space-y-4">
                                        <div className="flex items-center justify-between mb-2">
                                            <p className="text-sm font-bold text-amber-400 flex items-center gap-2">
                                                <i className="fa-solid fa-pen-to-square"></i>
                                                Verify {scanVerifyData.length} Extracted Receipt{scanVerifyData.length > 1 ? 's' : ''}
                                            </p>
                                            <button onClick={resetScanner} className="text-[10px] text-slate-400 hover:text-white underline">Cancel All</button>
                                        </div>

                                        <div className="space-y-4 max-h-[600px] overflow-y-auto pr-1">
                                            {scanVerifyData.map((data, index) => (
                                                <div key={index} className="bg-amber-950/30 border border-amber-700/30 rounded-xl p-4 space-y-3 relative">
                                                    <div className="absolute -top-2 -left-2 w-6 h-6 rounded-full bg-amber-600 text-white flex items-center justify-center text-xs font-bold shadow-lg border border-slate-950">
                                                        {index + 1}
                                                    </div>

                                                    {/* Source Filename */}
                                                    {data.filename && (
                                                        <div className="text-[10px] text-slate-500 font-mono pt-1 pb-2 truncate">
                                                            Source: {data.filename}
                                                        </div>
                                                    )}

                                                    {/* Editable fields grid */}
                                                    <div className="space-y-2 text-xs">
                                                        {/* Category + Date */}
                                                        <div className="grid grid-cols-2 gap-2">
                                                            <div>
                                                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">Category</label>
                                                                <select
                                                                    value={data.category || "Other"}
                                                                    onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], category: e.target.value }; return n; })}
                                                                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500"
                                                                >
                                                                    <option value="Fuel">Fuel</option>
                                                                    <option value="Maintenance">Maintenance</option>
                                                                    <option value="Vehicle">Vehicle</option>
                                                                    <option value="Other">Other</option>
                                                                    {!["Fuel", "Maintenance", "Vehicle", "Other"].includes(data.category) && data.category && (
                                                                        <option value={data.category}>{data.category}</option>
                                                                    )}
                                                                </select>
                                                            </div>
                                                            <div>
                                                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">Date</label>
                                                                <input type="date" value={data.expense_date || ""}
                                                                    onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], expense_date: e.target.value }; return n; })}
                                                                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                            </div>
                                                        </div>

                                                        {/* Amount */}
                                                        <div>
                                                            <label className="text-[10px] text-slate-500 uppercase tracking-wider">Total Amount (₹)</label>
                                                            <input type="number" step="0.01" value={data.amount || ""}
                                                                onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], amount: e.target.value }; return n; })}
                                                                className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                        </div>

                                                        {/* Invoice & GST */}
                                                        <div className="grid grid-cols-2 gap-2">
                                                            <div>
                                                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">Invoice No.</label>
                                                                <input type="text" value={data.invoice_number || ""}
                                                                    onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], invoice_number: e.target.value }; return n; })}
                                                                    placeholder="—"
                                                                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                            </div>
                                                            <div>
                                                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">GST Amount (₹)</label>
                                                                <input type="number" step="0.01" value={data.gst_amount || ""}
                                                                    onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], gst_amount: e.target.value }; return n; })}
                                                                    placeholder="—"
                                                                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                            </div>
                                                        </div>

                                                        {/* Vendor / Petrol Pump */}
                                                        <div className="grid grid-cols-2 gap-2">
                                                            <div>
                                                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">Vendor / Workshop</label>
                                                                <input type="text" value={data.vendor || ""}
                                                                    onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], vendor: e.target.value }; return n; })}
                                                                    placeholder="—"
                                                                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                            </div>
                                                            <div>
                                                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">Petrol Pump</label>
                                                                <input type="text" value={data.petrol_pump || ""}
                                                                    onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], petrol_pump: e.target.value }; return n; })}
                                                                    placeholder="—"
                                                                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                            </div>
                                                        </div>

                                                        {/* Reg No + Odometer */}
                                                        <div className="grid grid-cols-2 gap-2">
                                                            <div>
                                                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">Reg. No.</label>
                                                                <input type="text" value={data.registration_no || ""}
                                                                    onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], registration_no: e.target.value }; return n; })}
                                                                    placeholder="—"
                                                                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                            </div>
                                                            <div>
                                                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">Odometer (km)</label>
                                                                <input type="number" value={data.odometer || ""}
                                                                    onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], odometer: e.target.value }; return n; })}
                                                                    placeholder="—"
                                                                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                            </div>
                                                        </div>

                                                        {/* Liters + Rate */}
                                                        <div className="grid grid-cols-2 gap-2">
                                                            <div>
                                                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">Liters</label>
                                                                <input type="number" step="0.01" value={data.liters || ""}
                                                                    onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], liters: e.target.value }; return n; })}
                                                                    placeholder="—"
                                                                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                            </div>
                                                            <div>
                                                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">Rate/L (₹)</label>
                                                                <input type="number" step="0.01" value={data.rate_per_liter || ""}
                                                                    onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], rate_per_liter: e.target.value }; return n; })}
                                                                    placeholder="—"
                                                                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                            </div>
                                                        </div>

                                                        {/* Location + Service Type */}
                                                        <div className="grid grid-cols-2 gap-2">
                                                            <div>
                                                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">Location</label>
                                                                <input type="text" value={data.location || ""}
                                                                    onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], location: e.target.value }; return n; })}
                                                                    placeholder="—"
                                                                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                            </div>
                                                            <div>
                                                                <label className="text-[10px] text-slate-500 uppercase tracking-wider">Service Type</label>
                                                                <input type="text" value={data.service_type || ""}
                                                                    onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], service_type: e.target.value }; return n; })}
                                                                    placeholder="—"
                                                                    className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                            </div>
                                                        </div>

                                                        {/* Remarks */}
                                                        <div>
                                                            <label className="text-[10px] text-slate-500 uppercase tracking-wider">Remarks</label>
                                                            <input type="text" value={data.remarks || ""}
                                                                onChange={e => setScanVerifyData(p => { const n = [...p]; n[index] = { ...n[index], remarks: e.target.value }; return n; })}
                                                                className="w-full mt-1 bg-slate-950 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-1 focus:ring-amber-500" />
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>

                                        {/* Confirm & Save All */}
                                        <button
                                            onClick={handleConfirmAndSave}
                                            id="confirm-save-btn"
                                            className="w-full py-2.5 flex items-center justify-center gap-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold rounded-xl shadow-lg transition-all duration-300 text-xs mt-2"
                                        >
                                            <i className="fa-solid fa-circle-check"></i> Confirm & Save All {scanVerifyData.length}
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* ── MANUAL FORM (existing) ──────────────────── */}
                        {leftPanelMode === "manual" && (
                        <>
                        <h2 className="text-xl font-bold text-white mb-6 flex items-center">
                            <i className="fa-solid fa-file-invoice-dollar mr-2 text-indigo-400"></i>
                            Log New Expense
                        </h2>

                        <form onSubmit={handleSubmit} className="space-y-4">
                            {/* Category Select */}
                            <div>
                                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Category</label>
                                <select
                                    name="category"
                                    value={form.category}
                                    onChange={handleInputChange}
                                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                                >
                                    <option value="Fuel">Fuel</option>
                                    <option value="Maintenance">Maintenance</option>
                                    <option value="Vehicle">Vehicle</option>
                                    <option value="Other">Other</option>
                                </select>
                            </div>

                            {form.category === "Vehicle" && (
                                <div>
                                    <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Record Type</label>
                                    <select
                                        name="vehicle_record_type"
                                        value={form.vehicle_record_type}
                                        onChange={handleInputChange}
                                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                                    >
                                        <option value="general">General Vehicle</option>
                                        <option value="challan">Challan</option>
                                        <option value="parking">Parking</option>
                                        <option value="driver_cleaner">Driver / Cleaner</option>
                                        <option value="other">Other</option>
                                    </select>
                                </div>
                            )}

                            {/* Vehicle Name */}
                            <div>
                                <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Vehicle Nickname</label>
                                <input
                                    type="text"
                                    name="vehicle"
                                    placeholder="e.g. Scorpio, City, Duke"
                                    value={form.vehicle}
                                    onChange={handleInputChange}
                                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-white placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
                                />
                            </div>

                            {/* Amount & Date Grid */}
                            {!(form.category === "Vehicle" && ["parking", "other"].includes(form.vehicle_record_type)) && form.category !== "Other" && (
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Amount (₹)</label>
                                        <input
                                            type="number"
                                            step="0.01"
                                            name="amount"
                                            placeholder="0.00"
                                            required={!(form.category === "Vehicle" && ["parking", "other"].includes(form.vehicle_record_type))}
                                            value={form.amount}
                                            onChange={handleInputChange}
                                            className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-white placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Date</label>
                                        <input
                                            type="date"
                                            name="expense_date"
                                            required={!(form.category === "Vehicle" && ["parking", "other"].includes(form.vehicle_record_type))}
                                            value={form.expense_date}
                                            onChange={handleInputChange}
                                            className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                        />
                                    </div>
                                </div>
                            )}

                            {/* Parking Specific Section */}
                            {form.category === "Vehicle" && form.vehicle_record_type === "parking" && (
                                <div className="bg-emerald-950/20 p-4 border border-emerald-800/30 rounded-xl space-y-4">
                                    <p className="text-[10px] font-bold text-emerald-400 uppercase tracking-widest flex items-center">
                                        <i className="fa-solid fa-square-parking mr-2"></i> Parking Details
                                    </p>
                                    <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Parking Location</label>
                                            <input
                                                type="text"
                                                name="parking_location"
                                                placeholder="e.g. Mall, Airport"
                                                value={form.parking_location}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-xl px-4 py-2.5 text-sm text-white placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                                            />
                                        </div>
                                        <div>
                                            <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Amount (₹)</label>
                                            <input
                                                type="number"
                                                step="0.01"
                                                name="amount"
                                                placeholder="0.00"
                                                required={form.category === "Vehicle" && form.vehicle_record_type === "parking"}
                                                value={form.amount}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-emerald-500"
                                            />
                                        </div>
                                    </div>
                                    <div>
                                        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Expense Date</label>
                                        <input
                                            type="date"
                                            name="expense_date"
                                            required={form.category === "Vehicle" && form.vehicle_record_type === "parking"}
                                            value={form.expense_date}
                                            onChange={handleInputChange}
                                            className="w-full bg-slate-950 border border-slate-800/60 rounded-xl px-4 py-2 text-white focus:outline-none focus:ring-1 focus:ring-emerald-500"
                                        />
                                    </div>
                                </div>
                            )}

                            {/* Other Specific Section */}
                            {form.category === "Vehicle" && form.vehicle_record_type === "other" && (
                                <div className="bg-amber-950/20 p-4 border border-amber-800/30 rounded-xl space-y-4">
                                    <p className="text-[10px] font-bold text-amber-400 uppercase tracking-widest"><i className="fa-solid fa-layer-group mr-1.5"></i>Other Expense Details</p>

                                    <div className="grid grid-cols-2 gap-3">
                                        <div>
                                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Expense Name</label>
                                            <input
                                                type="text"
                                                name="expense_name"
                                                placeholder="e.g. Toll, Washing"
                                                value={form.expense_name}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-amber-500"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Amount (₹)</label>
                                            <input
                                                type="number"
                                                step="0.01"
                                                name="amount"
                                                placeholder="0.00"
                                                required={form.category === "Vehicle" && form.vehicle_record_type === "other"}
                                                value={form.amount}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-amber-500"
                                            />
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-2 gap-3">
                                        <div>
                                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Expense Date</label>
                                            <input
                                                type="date"
                                                name="expense_date"
                                                required={form.category === "Vehicle" && form.vehicle_record_type === "other"}
                                                value={form.expense_date}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-amber-500"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Location</label>
                                            <input
                                                type="text"
                                                name="location"
                                                placeholder="City or Area"
                                                value={form.location}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-amber-500"
                                            />
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-2 gap-3 pt-2 border-t border-amber-800/30">
                                        <div>
                                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Party Type</label>
                                            <input
                                                type="text"
                                                name="party_type"
                                                placeholder="e.g. Agency, Contractor"
                                                value={form.party_type}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-1 focus:ring-amber-500"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Party Name</label>
                                            <input
                                                type="text"
                                                name="party"
                                                placeholder="e.g. ABC Corp"
                                                value={form.party}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-1 focus:ring-amber-500"
                                            />
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Category: Other Specific Section */}
                            {form.category === "Other" && (
                                <div className="bg-fuchsia-950/20 p-4 border border-fuchsia-800/30 rounded-xl space-y-4">
                                    <p className="text-[10px] font-bold text-fuchsia-400 uppercase tracking-widest"><i className="fa-solid fa-asterisk mr-1.5"></i>Other Details</p>

                                    <div className="grid grid-cols-2 gap-3">
                                        <div>
                                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Category Name</label>
                                            <input
                                                type="text"
                                                name="expense_name"
                                                placeholder="e.g. Office Supplies"
                                                value={form.expense_name}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-fuchsia-500"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Amount (₹)</label>
                                            <input
                                                type="number"
                                                step="0.01"
                                                name="amount"
                                                placeholder="0.00"
                                                required={form.category === "Other"}
                                                value={form.amount}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-fuchsia-500"
                                            />
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-2 gap-3">
                                        <div>
                                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Expense Date</label>
                                            <input
                                                type="date"
                                                name="expense_date"
                                                required={form.category === "Other"}
                                                value={form.expense_date}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-fuchsia-500"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Contact Number</label>
                                            <input
                                                type="text"
                                                name="contact_number"
                                                placeholder="Phone Number"
                                                value={form.contact_number}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-fuchsia-500"
                                            />
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-2 gap-3 pt-2 border-t border-fuchsia-800/30">
                                        <div>
                                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Party Type</label>
                                            <input
                                                type="text"
                                                name="party_type"
                                                placeholder="e.g. Vendor, Employee"
                                                value={form.party_type}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-1 focus:ring-fuchsia-500"
                                            />
                                        </div>
                                        <div>
                                            <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Party Name</label>
                                            <input
                                                type="text"
                                                name="party"
                                                placeholder="e.g. John Doe"
                                                value={form.party}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-1 focus:ring-fuchsia-500"
                                            />
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Paid checkbox */}
                            <div className="flex items-center py-2">
                                <input
                                    id="paid"
                                    type="checkbox"
                                    name="paid"
                                    checked={form.paid}
                                    onChange={handleInputChange}
                                    className="w-4 h-4 text-indigo-600 bg-slate-950 border-slate-800 rounded focus:ring-indigo-500 focus:ring-offset-slate-900 focus:ring-offset-2"
                                />
                                <label htmlFor="paid" className="ml-2.5 text-sm text-slate-300 font-medium select-none cursor-pointer">
                                    {form.category === "Vehicle" && form.vehicle_record_type === "challan" ? "Mark challan as paid" : "Mark as Paid immediately"}
                                </label>
                            </div>

                            {/* Collapsible Advanced Form Info */}
                            <div className="border-t border-slate-800/80 pt-3">
                                <button
                                    type="button"
                                    onClick={() => setShowAdvanced(!showAdvanced)}
                                    className="flex items-center justify-between w-full text-xs font-bold text-slate-400 hover:text-slate-200 transition-colors uppercase tracking-wider py-1"
                                >
                                    <span>{showAdvanced ? "Hide Advanced Fields" : "Show Advanced Fields"}</span>
                                    <i className={`fa-solid ${showAdvanced ? "fa-chevron-up" : "fa-chevron-down"}`}></i>
                                </button>

                                {showAdvanced && (
                                    <div className="mt-4 space-y-4 animate-fadeIn">

                                        {/* Dynamic Fuel Specific Inputs */}
                                        {form.category === "Fuel" && (
                                            <div className="bg-slate-950/40 p-4 border border-slate-800/60 rounded-xl space-y-3">
                                                <p className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest"><i className="fa-solid fa-gas-pump mr-1.5"></i>Fuel Parameters</p>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div>
                                                        <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Liters</label>
                                                        <input
                                                            type="number"
                                                            step="0.01"
                                                            name="liters"
                                                            placeholder="0.00 L"
                                                            value={form.liters}
                                                            onChange={handleInputChange}
                                                            className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-cyan-500"
                                                        />
                                                    </div>
                                                    <div>
                                                        <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Rate/L (₹)</label>
                                                        <input
                                                            type="number"
                                                            step="0.01"
                                                            name="rate_per_liter"
                                                            placeholder="Rate"
                                                            value={form.rate_per_liter}
                                                            onChange={handleInputChange}
                                                            className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-cyan-500"
                                                        />
                                                    </div>
                                                </div>
                                                <div>
                                                    <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Petrol Pump Vendor</label>
                                                    <input
                                                        type="text"
                                                        name="petrol_pump"
                                                        placeholder="e.g. HP, Indian Oil"
                                                        value={form.petrol_pump}
                                                        onChange={handleInputChange}
                                                        className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-1 focus:ring-cyan-500"
                                                    />
                                                </div>
                                            </div>
                                        )}

                                        {form.category === "Vehicle" && form.vehicle_record_type === "challan" && (
                                            <div className="bg-indigo-950/20 p-4 border border-indigo-800/30 rounded-xl space-y-3">
                                                <p className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest"><i className="fa-solid fa-file-circle-exclamation mr-1.5"></i>Challan Details</p>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div>
                                                        <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Challan Number</label>
                                                        <input
                                                            type="text"
                                                            name="challan_no"
                                                            placeholder="e.g. MH-TRF-1024"
                                                            value={form.challan_no}
                                                            onChange={handleInputChange}
                                                            className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                                        />
                                                    </div>
                                                    <div>
                                                        <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Challan Type</label>
                                                        <input
                                                            type="text"
                                                            name="challan_type"
                                                            placeholder="e.g. Traffic"
                                                            value={form.challan_type}
                                                            onChange={handleInputChange}
                                                            className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                                        />
                                                    </div>
                                                </div>
                                                <div className="grid grid-cols-1 gap-3">
                                                    <div>
                                                        <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Due Date</label>
                                                        <input
                                                            type="date"
                                                            name="due_date"
                                                            value={form.due_date}
                                                            onChange={handleInputChange}
                                                            className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                                        />
                                                    </div>
                                                </div>
                                                <div className="grid grid-cols-2 gap-3">
                                                    <div>
                                                        <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Violation Type</label>
                                                        <input
                                                            type="text"
                                                            name="violation_type"
                                                            placeholder="e.g. No Parking"
                                                            value={form.violation_type}
                                                            onChange={handleInputChange}
                                                            className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                                        />
                                                    </div>
                                                    <div>
                                                        <label className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Issued By</label>
                                                        <input
                                                            type="text"
                                                            name="issued_by"
                                                            placeholder="e.g. Pune Traffic Police"
                                                            value={form.issued_by}
                                                            onChange={handleInputChange}
                                                            className="w-full bg-slate-950 border border-slate-800/60 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                                        />
                                                    </div>
                                                </div>
                                            </div>
                                        )}

                                        {/* Reg No & Odometer */}
                                        <div className="grid grid-cols-2 gap-3">
                                            <div>
                                                <label className="block text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Odometer (km)</label>
                                                <input
                                                    type="number"
                                                    name="odometer"
                                                    placeholder="e.g. 45200"
                                                    value={form.odometer}
                                                    onChange={handleInputChange}
                                                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                                />
                                            </div>
                                            <div>
                                                <label className="block text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Registration No</label>
                                                <input
                                                    type="text"
                                                    name="registration_no"
                                                    placeholder="MH12XY1234"
                                                    value={form.registration_no}
                                                    onChange={handleInputChange}
                                                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                                />
                                            </div>
                                        </div>

                                        {/* Service Type & Vendor */}
                                        {form.category === "Maintenance" && (
                                            <div className="grid grid-cols-2 gap-3">
                                                <div>
                                                    <label className="block text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Service Type</label>
                                                    <input
                                                        type="text"
                                                        name="service_type"
                                                        placeholder="e.g. Oil Change"
                                                        value={form.service_type}
                                                        onChange={handleInputChange}
                                                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="block text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Vendor/Workshop</label>
                                                    <input
                                                        type="text"
                                                        name="vendor"
                                                        placeholder="e.g. Service Center"
                                                        value={form.vendor}
                                                        onChange={handleInputChange}
                                                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                                    />
                                                </div>
                                            </div>
                                        )}

                                        {/* Location */}
                                        {!(form.category === "Vehicle" && ["parking", "other"].includes(form.vehicle_record_type)) && (
                                            <div>
                                                <label className="block text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">{form.category === "Vehicle" && form.vehicle_record_type === "challan" ? "Violation Location" : "Location"}</label>
                                                <input
                                                    type="text"
                                                    name="location"
                                                    placeholder="City or Area"
                                                    value={form.location}
                                                    onChange={handleInputChange}
                                                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                                />
                                            </div>
                                        )}

                                        {/* Remark */}
                                        <div>
                                            <label className="block text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Remark</label>
                                            <textarea
                                                name="remark"
                                                rows="2"
                                                placeholder="Add details or remarks..."
                                                value={form.remark}
                                                onChange={handleInputChange}
                                                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                            ></textarea>
                                        </div>

                                    </div>
                                )}
                            </div>

                            {/* Submit Button */}
                            <button
                                type="submit"
                                className="w-full mt-4 bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-3 px-4 rounded-xl shadow-lg shadow-indigo-600/20 hover:shadow-indigo-500/30 transition-all duration-300"
                            >
                                <i className="fa-solid fa-plus mr-2"></i> Save Expense Record
                            </button>
                        </form>
                        </>
                        )}

                    </div>
                </div>

                {/* Right Side: Filters, Tab Panels and Logs list (lg:span-8) */}
                <div className="lg:col-span-8 space-y-6">

                    {/* Filter, Search & Tabs Card */}
                    <div className="bg-slate-900/40 border border-slate-800 rounded-2xl p-5 space-y-4">

                        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">

                            {/* Search bar */}
                            <div className="relative flex-1">
                                <span className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-slate-500">
                                    <i className="fa-solid fa-magnifying-glass"></i>
                                </span>
                                <input
                                    type="text"
                                    placeholder="Search by vehicle, challan no, notes, location..."
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    className="w-full bg-slate-950 border border-slate-800 rounded-xl pl-10 pr-4 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                />
                            </div>

                            {/* Category Filter */}
                            <div className="w-full md:w-56">
                                <select
                                    value={categoryFilter}
                                    onChange={(e) => setCategoryFilter(e.target.value)}
                                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                >
                                    <option value="">All Categories</option>
                                    {availableCategories.map(cat => (
                                        <option key={cat} value={cat}>{cat}</option>
                                    ))}
                                </select>
                            </div>

                        </div>

                        {/* Tabs (All, Paid, Unpaid) */}
                        <div className="flex border-b border-slate-800/80 pt-2">
                            <button
                                onClick={() => setActiveTab("all")}
                                className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider border-b-2 transition-all ${activeTab === "all"
                                    ? "border-indigo-500 text-indigo-400"
                                    : "border-transparent text-slate-400 hover:text-slate-200"
                                    }`}
                            >
                                All Records
                            </button>
                            <button
                                onClick={() => setActiveTab("paid")}
                                className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider border-b-2 transition-all ${activeTab === "paid"
                                    ? "border-emerald-500 text-emerald-400"
                                    : "border-transparent text-slate-400 hover:text-slate-200"
                                    }`}
                            >
                                Paid
                            </button>
                            <button
                                onClick={() => setActiveTab("unpaid")}
                                className={`px-4 py-2.5 text-xs font-semibold uppercase tracking-wider border-b-2 transition-all ${activeTab === "unpaid"
                                    ? "border-amber-500 text-amber-400"
                                    : "border-transparent text-slate-400 hover:text-slate-200"
                                    }`}
                            >
                                Unpaid / Pending
                            </button>
                        </div>

                    </div>

                    {/* Logs Table / List Container */}
                    <div className="bg-slate-900/40 border border-slate-800 rounded-2xl overflow-hidden">

                        {loading ? (
                            <div className="p-20 text-center text-slate-500 space-y-4">
                                <i className="fa-solid fa-circle-notch fa-spin text-3xl text-indigo-400"></i>
                                <p className="text-sm">Fetching expense logs...</p>
                            </div>
                        ) : filteredExpenses.length === 0 ? (
                            <div className="p-20 text-center text-slate-500 space-y-4">
                                <i className="fa-solid fa-receipt text-4xl text-slate-700"></i>
                                <p className="text-sm">No expenses matched your search/filters.</p>
                            </div>
                        ) : (
                            <div className="overflow-x-auto">
                                <table className="w-full text-left border-collapse">
                                    <thead>
                                        <tr className="bg-slate-900/80 border-b border-slate-800 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                                            <th className="py-4 px-6">Expense Details</th>
                                            <th className="py-4 px-6 text-center">Category</th>
                                            <th className="py-4 px-6">Status</th>
                                            <th className="py-4 px-6 text-right">Amount</th>
                                            <th className="py-4 px-6 text-center">Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-800/60">
                                        {filteredExpenses.map((expense) => {

                                            // Category Color Tag
                                            let catColor = "bg-slate-800/80 text-slate-300 border-slate-700";
                                            let catIcon = "fa-receipt";
                                            if (expense.category === "Fuel") {
                                                catColor = "bg-cyan-950/40 text-cyan-400 border-cyan-800/40";
                                                catIcon = "fa-gas-pump";
                                            } else if (expense.category === "Maintenance") {
                                                catColor = "bg-purple-950/40 text-purple-400 border-purple-800/40";
                                                catIcon = "fa-wrench";
                                            } else if (expense.category === "Vehicle") {
                                                catColor = "bg-indigo-950/40 text-indigo-400 border-indigo-800/40";
                                                catIcon = "fa-car";
                                            } else if (expense.category === "Other") {
                                                catColor = "bg-slate-800/80 text-slate-300 border-slate-700";
                                                catIcon = "fa-receipt";
                                            } else {
                                                // Dynamic/custom category
                                                catColor = "bg-violet-950/40 text-violet-400 border-violet-800/40";
                                                catIcon = "fa-wand-magic-sparkles";
                                            }

                                            return (
                                                <tr
                                                    key={expense.expense_id}
                                                    onClick={() => setSelectedExpense(expense)}
                                                    className="hover:bg-slate-800/30 transition-colors cursor-pointer group"
                                                >
                                                    <td className="py-4 px-6">
                                                        <div className="font-semibold text-white group-hover:text-indigo-400 transition-colors text-sm">
                                                            {getRecordTitle(expense)}
                                                        </div>
                                                        <div className="text-xs text-slate-500 mt-0.5 flex items-center gap-2">
                                                            <span>{formatDate(expense.expense_date)}</span>
                                                            {isChallanExpense(expense) && expense.challan_type && (
                                                                <>
                                                                    <span className="text-slate-700">•</span>
                                                                    <span>{expense.challan_type}</span>
                                                                </>
                                                            )}
                                                            {expense.registration_no && (
                                                                <>
                                                                    <span className="text-slate-700">•</span>
                                                                    <span className="uppercase">{expense.registration_no}</span>
                                                                </>
                                                            )}
                                                        </div>
                                                        {isChallanExpense(expense) && expense.violation_type && (
                                                            <div className="text-xs text-slate-400 mt-1">
                                                                {expense.violation_type}
                                                            </div>
                                                        )}
                                                    </td>
                                                    <td className="py-4 px-6 text-center">
                                                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${catColor}`}>
                                                            <i className={`fa-solid ${catIcon} text-[10px]`}></i>
                                                            {expense.category}
                                                        </span>
                                                    </td>
                                                    <td className="py-4 px-6">
                                                        {expense.paid ? (
                                                            <span className="inline-flex items-center text-xs font-semibold text-emerald-400">
                                                                <span className="w-1.5 h-1.5 mr-1.5 bg-emerald-400 rounded-full"></span>
                                                                Paid
                                                            </span>
                                                        ) : (
                                                            <span className="inline-flex items-center text-xs font-semibold text-amber-400 animate-pulse">
                                                                <span className="w-1.5 h-1.5 mr-1.5 bg-amber-400 rounded-full"></span>
                                                                Pending
                                                            </span>
                                                        )}
                                                    </td>
                                                    <td className="py-4 px-6 text-right font-bold text-white text-sm">
                                                        ₹{(Number(expense.amount) || 0).toFixed(2)}
                                                    </td>
                                                    <td className="py-4 px-6 text-center" onClick={(e) => e.stopPropagation()}>
                                                        <div className="flex items-center justify-center gap-2">
                                                            <button
                                                                onClick={() => setSelectedExpense(expense)}
                                                                className="p-1.5 text-slate-400 hover:text-indigo-400 hover:bg-slate-800 rounded-lg transition-colors"
                                                                title="View Details"
                                                            >
                                                                <i className="fa-solid fa-eye text-xs"></i>
                                                            </button>
                                                            <button
                                                                onClick={(e) => handleDelete(expense.expense_id, e)}
                                                                className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-slate-800 rounded-lg transition-colors"
                                                                title="Delete"
                                                            >
                                                                <i className="fa-solid fa-trash-can text-xs"></i>
                                                            </button>
                                                        </div>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}

                    </div>

                </div>

            </div>

            {/* View Details Modal */}
            {selectedExpense && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fadeIn">
                    <div className="w-full max-w-lg bg-[#0e1424] border border-slate-800 rounded-3xl overflow-hidden shadow-2xl animate-scaleIn">

                        {/* Modal Header */}
                        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-800/80 bg-slate-900/50">
                            <div>
                                <h3 className="text-lg font-bold text-white flex items-center">
                                    <i className="fa-solid fa-circle-info mr-2 text-indigo-400"></i>
                                    Expense Details
                                </h3>
                                <p className="text-xs text-indigo-400/80 font-medium mt-1">ID: #{selectedExpense.expense_id}</p>
                            </div>
                            <button
                                onClick={() => setSelectedExpense(null)}
                                className="w-8 h-8 flex items-center justify-center text-slate-400 hover:text-white bg-slate-850 hover:bg-slate-800 rounded-full transition-colors"
                            >
                                <i className="fa-solid fa-xmark"></i>
                            </button>
                        </div>

                        {/* Modal Body */}
                        <div className="p-6 space-y-6 max-h-[70vh] overflow-y-auto">

                            {/* Primary Details Row */}
                            <div className="grid grid-cols-2 gap-4">
                                <div className="bg-slate-950/40 p-4 rounded-2xl border border-slate-800/40 text-center">
                                    <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Amount</p>
                                    <p className="text-2xl font-extrabold text-white mt-1">₹{(Number(selectedExpense.amount) || 0).toFixed(2)}</p>
                                </div>
                                <div className="bg-slate-950/40 p-4 rounded-2xl border border-slate-800/40 text-center">
                                    <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Date</p>
                                    <p className="text-md font-bold text-indigo-300 mt-2">
                                        {formatDate(selectedExpense.expense_date, {
                                            day: '2-digit', month: 'long', year: 'numeric'
                                        })}
                                    </p>
                                </div>
                            </div>

                            {/* Core Specs Grid */}
                            <div className="grid grid-cols-2 gap-y-4 gap-x-6 text-sm">
                                <div>
                                    <span className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider">Category</span>
                                    <span className="font-semibold text-white mt-0.5 inline-block">{selectedExpense.category}</span>
                                </div>
                                <div>
                                    <span className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider">Vehicle</span>
                                    <span className="font-semibold text-white mt-0.5 inline-block">{selectedExpense.vehicle || "General (No vehicle)"}</span>
                                </div>
                                <div>
                                    <span className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider">Status</span>
                                    <span className={`inline-flex items-center text-xs font-bold mt-1 ${selectedExpense.paid ? "text-emerald-400" : "text-amber-400"}`}>
                                        <span className={`w-2 h-2 mr-2 rounded-full ${selectedExpense.paid ? "bg-emerald-400" : "bg-amber-400 animate-pulse"}`}></span>
                                        {selectedExpense.paid ? "Fully Settled" : "Awaiting Payment"}
                                    </span>
                                </div>
                                <div>
                                    <span className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider">Registration Number</span>
                                    <span className="font-semibold text-white uppercase mt-0.5 inline-block">{selectedExpense.registration_no || "N/A"}</span>
                                </div>
                                <div>
                                    <span className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider">Odometer Reading</span>
                                    <span className="font-semibold text-white mt-0.5 inline-block">
                                        {selectedExpense.odometer ? `${selectedExpense.odometer.toLocaleString()} km` : "N/A"}
                                    </span>
                                </div>
                                <div>
                                    <span className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider">{isChallanExpense(selectedExpense) ? "Violation Location" : "Location / City"}</span>
                                    <span className="font-semibold text-white mt-0.5 inline-block">{selectedExpense.location || "N/A"}</span>
                                </div>
                            </div>

                            {/* Vehicle / Challan Specific Block */}
                            {isChallanExpense(selectedExpense) && (
                                <div className="bg-indigo-950/15 p-4 border border-indigo-800/20 rounded-2xl space-y-3">
                                    <p className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest"><i className="fa-solid fa-file-circle-exclamation mr-1.5"></i>Challan Record</p>
                                    <div className="grid grid-cols-2 gap-3 text-xs">
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Challan No</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.challan_no || "N/A"}</span>
                                        </div>
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Challan Type</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.challan_type || "N/A"}</span>
                                        </div>
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Due Date</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{formatDate(selectedExpense.due_date)}</span>
                                        </div>
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Violation Type</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.violation_type || "N/A"}</span>
                                        </div>
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Issued By</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.issued_by || "N/A"}</span>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Parking Specific Block */}
                            {(selectedExpense.category === "Vehicle" && selectedExpense.service_type === "parking") && (
                                <div className="bg-emerald-950/15 p-4 border border-emerald-800/20 rounded-2xl space-y-3">
                                    <p className="text-[10px] font-bold text-emerald-400 uppercase tracking-widest"><i className="fa-solid fa-square-parking mr-1.5"></i>Parking Record Breakdown</p>
                                    <div className="grid grid-cols-2 gap-2 text-xs">
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Parking Location</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.location || "N/A"}</span>
                                        </div>
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Fees Paid</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">₹{selectedExpense.amount.toFixed(2)}</span>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Other Specific Block */}
                            {(selectedExpense.category === "Vehicle" && selectedExpense.service_type === "other") && (
                                <div className="bg-amber-950/15 p-4 border border-amber-800/20 rounded-2xl space-y-3">
                                    <p className="text-[10px] font-bold text-amber-400 uppercase tracking-widest"><i className="fa-solid fa-layer-group mr-1.5"></i>Other Record Details</p>
                                    <div className="grid grid-cols-2 gap-3 text-xs">
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Expense Name</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.expense_name || "N/A"}</span>
                                        </div>
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Location</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.location || "N/A"}</span>
                                        </div>
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Party Type</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.party_type || "N/A"}</span>
                                        </div>
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Party Name</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.party || "N/A"}</span>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Fuel Specific Block */}
                            {selectedExpense.category === "Fuel" && (selectedExpense.liters || selectedExpense.rate_per_liter || selectedExpense.petrol_pump) && (
                                <div className="bg-cyan-950/15 p-4 border border-cyan-800/20 rounded-2xl space-y-3">
                                    <p className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest"><i className="fa-solid fa-gas-pump mr-1.5"></i>Fuel Record Breakdown</p>
                                    <div className="grid grid-cols-3 gap-2 text-xs">
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Liters</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.liters ? `${selectedExpense.liters} L` : "N/A"}</span>
                                        </div>
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Rate/L</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.rate_per_liter ? `₹${selectedExpense.rate_per_liter}` : "N/A"}</span>
                                        </div>
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Petrol Station</span>
                                            <span className="font-bold text-white mt-0.5 inline-block truncate w-24" title={selectedExpense.petrol_pump}>{selectedExpense.petrol_pump || "N/A"}</span>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Service / Vendor Specific Block */}
                            {(selectedExpense.service_type || selectedExpense.vendor) && (
                                <div className="bg-purple-950/15 p-4 border border-purple-800/20 rounded-2xl space-y-3">
                                    <p className="text-[10px] font-bold text-purple-400 uppercase tracking-widest"><i className="fa-solid fa-wrench mr-1.5"></i>Service Record Details</p>
                                    <div className="grid grid-cols-2 gap-2 text-xs">
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Service Type</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.service_type || "N/A"}</span>
                                        </div>
                                        <div>
                                            <span className="block text-[10px] text-slate-500 uppercase">Vendor Workshop</span>
                                            <span className="font-bold text-white mt-0.5 inline-block">{selectedExpense.vendor || "N/A"}</span>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Dynamic Extracted Fields Breakdown */}
                            {(() => {
                                const coreRenderedKeys = [
                                    "expense_id", "category", "vehicle", "expense_date", "amount", 
                                    "paid", "registration_no", "odometer", "location", "remarks", 
                                    "remark", "raw_text", "scanned_image", "filename", "latency_seconds"
                                ];

                                const categoryKeys = [];
                                if (isChallanExpense(selectedExpense)) {
                                    categoryKeys.push("challan_no", "challan_type", "due_date", "violation_type", "issued_by");
                                }
                                if (selectedExpense.category === "Vehicle" && selectedExpense.service_type === "parking") {
                                    categoryKeys.push("parking_location");
                                }
                                if (selectedExpense.category === "Vehicle" && selectedExpense.service_type === "other") {
                                    categoryKeys.push("expense_name", "party_type", "party");
                                }
                                if (selectedExpense.category === "Fuel") {
                                    categoryKeys.push("liters", "rate_per_liter", "petrol_pump");
                                }
                                if (selectedExpense.service_type || selectedExpense.vendor) {
                                    categoryKeys.push("service_type", "vendor");
                                }

                                const excludedKeys = [...coreRenderedKeys, ...categoryKeys];
                                
                                const additionalFields = Object.entries(selectedExpense).filter(([key, val]) => {
                                    if (val === null || val === undefined || val === "") return false;
                                    return !excludedKeys.includes(key);
                                });

                                if (additionalFields.length === 0) return null;

                                return (
                                    <div className="bg-slate-900/40 p-4 border border-slate-800/60 rounded-2xl space-y-3">
                                        <p className="text-[10px] font-bold text-indigo-400 uppercase tracking-widest">
                                            <i className="fa-solid fa-list-check mr-1.5"></i>Additional Details
                                        </p>
                                        <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-xs">
                                            {additionalFields.map(([key, val]) => {
                                                // Format key beautifully
                                                let displayKey = key.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
                                                if (displayKey.startsWith("Gst ")) {
                                                    displayKey = "GST " + displayKey.slice(4);
                                                }
                                                if (displayKey.startsWith("Tds ")) {
                                                    displayKey = "TDS " + displayKey.slice(4);
                                                }
                                                if (displayKey === "Km Limit") {
                                                    displayKey = "KM Limit";
                                                }

                                                // Format values beautifully
                                                let displayVal = val;
                                                if (typeof val === "boolean") {
                                                    displayVal = val ? "Yes" : "No";
                                                } else if (typeof val === "number" && (key.includes("amount") || key.includes("charges") || key.includes("rate") || key.includes("allowance"))) {
                                                    displayVal = `₹${val.toFixed(2)}`;
                                                } else if (typeof val === "number" && (key === "odometer" || key.includes("odometer_reading") || key === "next_service_due")) {
                                                    displayVal = `${val.toLocaleString()} km`;
                                                } else if (typeof val === "number" && key === "liters") {
                                                    displayVal = `${val} L`;
                                                } else if (key.includes("date") && typeof val === "string") {
                                                    displayVal = formatDate(val);
                                                }

                                                return (
                                                    <div key={key} className="break-words">
                                                        <span className="block text-[10px] text-slate-500 uppercase">{displayKey}</span>
                                                        <span className="font-bold text-white mt-0.5 inline-block">{displayVal}</span>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </div>
                                );
                            })()}


                            {/* Description / Notes Block */}
                            <div>
                                <span className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Notes / Remarks</span>
                                <div className="bg-slate-950/40 p-4 rounded-xl border border-slate-850 text-sm text-slate-300 italic min-h-[60px]">
                                    {selectedExpense.remarks || selectedExpense.remark || "No remarks recorded for this log entry."}
                                </div>
                            </div>

                        </div>

                        {/* Modal Footer */}
                        <div className="flex items-center justify-end gap-3 px-6 py-4 bg-slate-900/50 border-t border-slate-800/80">
                            <button
                                onClick={() => setSelectedExpense(null)}
                                className="px-5 py-2 text-sm font-semibold text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-xl transition-colors"
                            >
                                Close Panel
                            </button>
                            <button
                                onClick={(e) => handleDelete(selectedExpense.expense_id, e)}
                                className="px-5 py-2 text-sm font-semibold text-white bg-rose-600 hover:bg-rose-500 hover:shadow-lg hover:shadow-rose-600/10 rounded-xl transition-all"
                            >
                                <i className="fa-solid fa-trash-can mr-2"></i>Delete Record
                            </button>
                        </div>

                    </div>
                </div>
            )}
        </div>
    );
}

// Mount the App to root
const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
