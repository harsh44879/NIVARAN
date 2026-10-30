const department = document.getElementById("department");
const complaintCategory = document.getElementById("complaint_category");

const categories = {
    "Water Department": [
        "Water Leakage",
        "Dirty Water",
        "Broken Pipeline",
        "No Water Supply",
        "Low Water Pressure"
    ],
    "Electricity Department": [
        "Street Light Not Working",
        "Power Cut",
        "Sparking Wire",
        "Transformer Issue",
        "Electric Pole Damage"
    ],
    "Road Department": [
        "Potholes",
        "Road Cracks",
        "Water Logging On Road",
        "Damaged Footpath"
    ]
};

if (department && complaintCategory) {
    department.addEventListener("change", function () {
        const selectedDept = department.value;
        complaintCategory.innerHTML = "";

        const defaultOption = document.createElement("option");
        defaultOption.value = "";
        defaultOption.textContent = "Select Issue Category";
        defaultOption.disabled = true;
        defaultOption.selected = true;
        complaintCategory.appendChild(defaultOption);

        if (categories[selectedDept]) {
            categories[selectedDept].forEach(function (cat) {
                const opt = document.createElement("option");
                opt.value = cat;
                opt.textContent = cat;
                complaintCategory.appendChild(opt);
            });
        }
    });
}
