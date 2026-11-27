
import pytest

from member3_output import (
    sanitize_relative_path,
    sanitize_csv_header,
    redact_json_values,
    sanitize_json_keys,
    detect_sensitive_path_components
)


def test_sensitive_filename_is_replaced():
    input_path = "registration/ramesh_9876543210.csv"

    safe_path = sanitize_relative_path(
        input_path, {1}, replacement_id="001"
    )

    assert safe_path == "registration/record_001.csv"


def test_sensitive_folder_and_filename_are_replaced():
    input_path = "ramesh/9876543210.csv"

    safe_path = sanitize_relative_path(
        input_path, {0, 1}, replacement_id="002"
    )

    assert safe_path == "folder_1/record_002.csv"


def test_safe_path_is_preserved():
    input_path = "lab/reports/results.csv"

    safe_path = sanitize_relative_path(input_path, set())

    assert safe_path == input_path


def test_file_extension_is_preserved():
    input_path = "registration/patient_data.tar.gz"

    safe_path = sanitize_relative_path(
        input_path, {1}, replacement_id="003"
    )

    assert safe_path == "registration/record_003.tar.gz"


def test_duplicate_output_paths_are_prevented():
    used_paths = set()

    first_path = sanitize_relative_path(
        "registration/patient_one.csv",
        {1},
        used_paths,
        "001"
    )

    second_path = sanitize_relative_path(
        "registration/patient_two.csv",
        {1},
        used_paths,
        "001"
    )

    assert first_path == "registration/record_001.csv"
    assert second_path == "registration/record_001_2.csv"
    assert len(used_paths) == 2


def test_parent_directory_traversal_is_rejected():
    with pytest.raises(ValueError):
        sanitize_relative_path("../patient.csv", {1})


def test_absolute_path_is_rejected():
    with pytest.raises(ValueError):
        sanitize_relative_path("/private/patient.csv", {1})


def test_invalid_component_index_is_rejected():
    with pytest.raises(ValueError):
        sanitize_relative_path("registration/patient.csv", {5})


# CSV HEADER TESTS

def test_sensitive_csv_header_is_replaced():
    headers = [
        "Patient_Ramesh",
        "Phone_Number",
        "Medicine",
        "Dosage"
    ]

    safe_headers = sanitize_csv_header(headers, {0})

    assert safe_headers == [
        "protected_field_1",
        "Phone_Number",
        "Medicine",
        "Dosage"
    ]


def test_clinical_headers_are_preserved():
    headers = [
        "Medicine",
        "Dosage",
        "Diagnosis",
        "Lab_Value"
    ]

    safe_headers = sanitize_csv_header(headers, set())

    assert safe_headers == headers


def test_duplicate_header_names_are_avoided():
    headers = [
        "Patient_Name",
        "protected_field_1",
        "Medicine"
    ]

    safe_headers = sanitize_csv_header(headers, {0})

    assert safe_headers == [
        "protected_field_1_2",
        "protected_field_1",
        "Medicine"
    ]


def test_invalid_header_index_is_rejected():
    with pytest.raises(ValueError):
        sanitize_csv_header(["Name", "Medicine"], {5})


def test_json_patient_name_is_redacted():
    data = {
        "patient": {
            "name": "Ramesh",
            "medicine": "Paracetamol"
        }
    }

    result = redact_json_values(data, ["/patient/name"])

    assert result["patient"]["name"] == "[REDACTED]"
    assert result["patient"]["medicine"] == "Paracetamol"


def test_json_medical_values_are_preserved():
    data = {
        "medicine": "Paracetamol",
        "dosage": "500mg",
        "diagnosis": "Fever"
    }

    result = redact_json_values(data, [])

    assert result == data


def test_json_array_value_is_redacted():
    data = {
        "patients": [
            {"name": "Ramesh"},
            {"name": "Sita"}
        ]
    }

    result = redact_json_values(
        data,
        ["/patients/0/name"]
    )

    assert result["patients"][0]["name"] == "[REDACTED]"
    assert result["patients"][1]["name"] == "Sita"


def test_original_json_is_not_modified():
    data = {
        "patient": {
            "name": "Ramesh"
        }
    }

    result = redact_json_values(data, ["/patient/name"])

    assert data["patient"]["name"] == "Ramesh"
    assert result["patient"]["name"] == "[REDACTED]"


def test_invalid_json_location_is_rejected():
    data = {"patient": {"name": "Ramesh"}}

    try:
        redact_json_values(data, ["/patient/phone"])
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_sensitive_json_key_is_renamed():
    data = {
        "patient": {
            "Ramesh Kumar": "Patient Name",
            "medicine": "Paracetamol"
        }
    }

    result = sanitize_json_keys(
        data, ["/patient/Ramesh Kumar"]
    )

    assert "protected_field" in result["patient"]
    assert result["patient"]["protected_field"] == "Patient Name"
    assert result["patient"]["medicine"] == "Paracetamol"


def test_json_key_collision_is_avoided():
    data = {
        "patient": {
            "Ramesh": "Patient Name",
            "protected_field": "Existing value"
        }
    }

    result = sanitize_json_keys(data, ["/patient/Ramesh"])

    assert result["patient"]["protected_field_2"] == "Patient Name"
    assert result["patient"]["protected_field"] == "Existing value"


def test_json_key_inside_array_is_renamed():
    data = {
        "patients": [
            {"Ramesh": "Patient Name"}
        ]
    }

    result = sanitize_json_keys(
        data, ["/patients/0/Ramesh"]
    )

    assert result["patients"][0]["protected_field"] == "Patient Name"


def test_original_json_keys_are_preserved():
    data = {"patient": {"Ramesh": "Patient Name"}}

    result = sanitize_json_keys(data, ["/patient/Ramesh"])

    assert "Ramesh" in data["patient"]
    assert "Ramesh" not in result["patient"]


def test_missing_json_key_is_rejected():
    data = {"patient": {"medicine": "Paracetamol"}}

    with pytest.raises(ValueError):
        sanitize_json_keys(data, ["/patient/Ramesh"])


def test_phone_number_in_filename_is_detected():
    assert detect_sensitive_path_components(
        "registration/patient_9876543210.csv"
    ) == [1]


def test_email_in_filename_is_detected():
    assert detect_sensitive_path_components(
        "registration/rahul@example.com.json"
    ) == [1]


def test_safe_filename_is_not_flagged():
    assert detect_sensitive_path_components(
        "registration/lab_report.csv"
    ) == []


from modules.header_classification import classify_csv_column


def test_registration_headers_are_classified():
    expected = {
        "UHID": "UHID",
        "Patient Name": "PATIENT_NAME",
        "Relative Name": "RELATIVE_NAME",
        "Village/Mohalla": "ADDRESS",
        "Tehsil": "ADDRESS",
        "District": "ADDRESS",
        "PIN": "PIN",
        "Mobile": "PHONE",
        "Aadhaar No": "AADHAAR",
        "ABHA No": "ABHA",
        "Reg Date": "DATE",
        "DOB": "DOB",
        "Age": "AGE",
        "Gender": None,
        "Relation": None
    }

    for header, category in expected.items():
        assert classify_csv_column(header) == category

def test_sensitive_folder_and_filename_are_detected():
    assert detect_sensitive_path_components(
        "9876543210/record_123456789012.csv"
    ) == [0, 1]


def test_hinglish_registration_headers_are_classified():
    from modules.header_classification import classify_csv_column

    expected = {
        "Reg No": "UHID",
        "Naam": "PATIENT_NAME",
        "Ling": None,
        "Umar": "AGE",
        "Janm Tithi": "DOB",
        "Pita/Pati ka Naam": "RELATIVE_NAME",
        "Pata": "ADDRESS",
        "Gaon": "ADDRESS",
        "Tehsil": "ADDRESS",
        "Jila": "ADDRESS",
        "Pin Code": "PIN",
        "Mobile No": "PHONE",
        "Aadhar": "AADHAAR",
        "Registration Date": "DATE"
    }

    for header, expected_category in expected.items():
        assert classify_csv_column(header) == expected_category

def test_arogya_registration_headers():
    from modules.header_classification import classify_csv_column

    expected = {
        "PatientID": "UHID",
        "LastName": "PATIENT_NAME",
        "FirstName": "PATIENT_NAME",
        "Sex": None,
        "DOB (MM/DD/YYYY)": "DOB",
        "Guardian": "RELATIVE_NAME",
        "Street": "ADDRESS",
        "City": "ADDRESS",
        "District": "ADDRESS",
        "Zip": "PIN",
        "Phone": "PHONE",
        "Email": None,
        "Registered (MM/DD/YYYY)": "DATE",
        "Notes": None
    }

    for header, category in expected.items():
        assert classify_csv_column(header) == category
        
if __name__ == "__main__":
    pytest.main(["-v", __file__])


