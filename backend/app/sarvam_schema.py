"""Extraction schema submitted to the Sarvam doc-AI API.

The schema follows the documented Sarvam doc Intelligence response format. Sarvam
returns a JSON object matching these properties, which is mapped to timetables by
``app.sarvam_mapping``.
"""

SCHEMA = {
    "properties": {
        "department_name": {
            "aliases": [],
            "description": "The full name of the academic department that manages the timetable.",
            "placement": {
                "look_for": "the top header of the page",
                "placement_description": "The running header at the very top of every page.",
                "placement_tier": "document_summary",
                "section": None
            },
            "type": "string",
            "x-field-id": "fld_18fdde5d54b2"
        },
        "academic_year": {
            "aliases": [
                "Session"
            ],
            "description": "The specific academic year for which the schedule is valid, typically formatted as a range of years.\nLabels: Session",
            "placement": {
                "look_for": "the label 'Session'",
                "placement_description": "Located in the header information block at the top of the page.",
                "placement_tier": "document_summary",
                "section": None
            },
            "type": "string",
            "x-field-id": "fld_90b450ba2789"
        },
        "session": {
            "aliases": [
                "Session"
            ],
            "description": "The academic session identifier associated with the timetable.\nLabels: Session",
            "placement": {
                "look_for": "the label 'Session'",
                "placement_description": "Located in the header information block at the top of the page.",
                "placement_tier": "document_summary",
                "section": None
            },
            "type": "string",
            "x-field-id": "fld_b5d973f255d0"
        },
        "class": {
            "aliases": [
                "Class"
            ],
            "description": "The identifier for the specific class or section, including the semester and section letter.\nLabels: Class",
            "placement": {
                "look_for": "the label 'Class'",
                "placement_description": "Located in the header information block at the top of the page.",
                "placement_tier": "document_summary",
                "section": None
            },
            "type": "string",
            "x-field-id": "fld_623152be1332"
        },
        "semester": {
            "aliases": [
                "Class"
            ],
            "description": "The academic semester of the students for the given class.\nLabels: Class",
            "placement": {
                "look_for": "the value following 'semester' within the 'Class' field",
                "placement_description": "Embedded within the 'Class' label value in the header block.",
                "placement_tier": "document_summary",
                "section": None
            },
            "type": "string",
            "x-field-id": "fld_df018a44d314"
        },
        "program_or_specialization": {
            "aliases": [
                "Class"
            ],
            "description": "The degree program or academic specialization of the students in the class.\nLabels: Class",
            "placement": {
                "look_for": "the value in parentheses within the 'Class' field",
                "placement_description": "Embedded within the 'Class' label value in the header block.",
                "placement_tier": "document_summary",
                "section": None
            },
            "type": "string",
            "x-field-id": "fld_74972094b6fd"
        },
        "room_number": {
            "aliases": [
                "Room No."
            ],
            "description": "The room number or identifier where the class sessions are held.\nLabels: Room No.",
            "placement": {
                "look_for": "the label 'Room No.'",
                "placement_description": "Located in the header information block at the top of the page.",
                "placement_tier": "document_summary",
                "section": None
            },
            "type": "string",
            "x-field-id": "fld_a74d9649bcc0"
        },
        "class_teacher": {
            "aliases": [
                "Class Teacher"
            ],
            "description": "The full name of the faculty member designated as the class teacher.\nLabels: Class Teacher",
            "placement": {
                "look_for": "the label 'Class Teacher'",
                "placement_description": "Located in the header information block at the top of the page.",
                "placement_tier": "document_summary",
                "section": None
            },
            "type": "string",
            "x-field-id": "fld_6f149c64a354"
        },
        "staff_names": {
            "aliases": [
                "Faculty/Sign"
            ],
            "description": "The full names of faculty members assigned to courses.\nLabels: Faculty/Sign",
            "placement": {
                "ambiguity_resolve": "first_row",
                "instance_group": "subject_list",
                "look_for": "the column header 'Faculty/Sign'",
                "placement_description": "A row in the subject mapping table located in the lower half of the page.",
                "placement_tier": "repeated_instance",
                "section": None
            },
            "type": "string",
            "x-field-id": "fld_ea74bfe01849"
        },
        "subject_assignments": {
            "aliases": [
                "Subject",
                "Faculty/Sign"
            ],
            "description": "The mapping of specific subjects to the faculty members responsible for teaching them.\nLabels: Subject, Faculty/Sign",
            "placement": {
                "ambiguity_resolve": "first_row",
                "instance_group": "subject_list",
                "look_for": "the table containing 'Subject' and 'Faculty/Sign' columns",
                "placement_description": "The relationship between the subject name and the faculty name in the subject mapping table.",
                "placement_tier": "repeated_instance",
                "section": None
            },
            "type": "string",
            "x-field-id": "fld_4a9d84a546ed"
        },
        "institution": {
            "description": "The name of the college or university institution.",
            "placement": {
                "section": None
            },
            "type": "string",
            "x-field-id": "fld_119133a3b78d"
        },
        "time_slot": {
            "description": "A table where each row represents a unique time interval defined in the timetable's time grid.",
            "items": {
                "properties": {
                    "start_time": {
                        "aliases": [
                            "Time"
                        ],
                        "description": "The exact start time of the time slot.\nLabels: Time",
                        "placement": {
                            "instance_group": "timetable_col",
                            "look_for": "the time range headers at the top of the timetable grid",
                            "placement_description": "The column headers indicating time slots in the timetable grid.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_7142278c20e7"
                    },
                    "end_time": {
                        "aliases": [
                            "Time"
                        ],
                        "description": "The exact end time of the time slot.\nLabels: Time",
                        "placement": {
                            "instance_group": "timetable_col",
                            "look_for": "the time range headers at the top of the timetable grid",
                            "placement_description": "The column headers indicating time slots in the timetable grid.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_cf393af6a483"
                    }
                },
                "type": "object"
            },
            "type": "array",
            "x-field-id": "fld_45f0def01a05"
        },
        "weekly_schedule": {
            "description": "A table where each row represents a single scheduled assignment or activity for a specific day and time.",
            "items": {
                "properties": {
                    "day": {
                        "aliases": [
                            "Day"
                        ],
                        "description": "The day of the week for the scheduled assignment.\nLabels: Day",
                        "placement": {
                            "ambiguity_resolve": "first_row",
                            "instance_group": "timetable_row",
                            "look_for": "the 'Day' column header in the timetable grid",
                            "placement_description": "The first column of the main timetable grid.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_e8a146c86022"
                    },
                    "start_time": {
                        "aliases": [
                            "Time"
                        ],
                        "description": "The start time of the specific assignment.\nLabels: Time",
                        "placement": {
                            "instance_group": "timetable_col",
                            "look_for": "the time range headers at the top of the timetable grid",
                            "placement_description": "The column headers indicating time slots in the timetable grid.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_2858962899a1"
                    },
                    "end_time": {
                        "aliases": [
                            "Time"
                        ],
                        "description": "The end time of the specific assignment.\nLabels: Time",
                        "placement": {
                            "instance_group": "timetable_col",
                            "look_for": "the time range headers at the top of the timetable grid",
                            "placement_description": "The column headers indicating time slots in the timetable grid.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_0a4ebfeb5b09"
                    },
                    "subject_abbreviation": {
                        "description": "The short-form code or abbreviation used to represent the subject in the timetable grid.",
                        "placement": {
                            "instance_group": "timetable_cell",
                            "look_for": "the text within the cells of the timetable grid",
                            "placement_description": "The content of the cells in the timetable grid intersecting a day and time.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_2573c0562831"
                    },
                    "subject_name": {
                        "aliases": [
                            "Subject"
                        ],
                        "description": "The full descriptive name of the subject.\nLabels: Subject",
                        "placement": {
                            "ambiguity_resolve": "first_row",
                            "instance_group": "subject_list_row",
                            "look_for": "the 'Subject' column in the subject list table",
                            "placement_description": "The second column of the subject mapping table located below the timetable grid.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_a3d597ed4fec"
                    },
                    "subject_code": {
                        "aliases": [
                            "Sub Code"
                        ],
                        "description": "The unique alphanumeric code assigned to the subject.\nLabels: Sub Code",
                        "placement": {
                            "ambiguity_resolve": "first_row",
                            "instance_group": "subject_list_row",
                            "look_for": "the 'Sub Code' column in the subject list table",
                            "placement_description": "The first column of the subject mapping table located below the timetable grid.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_40cda2a5c70f"
                    },
                    "session_type": {
                        "description": "The category of the session, such as a lecture, practical, or training.",
                        "placement": {
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_9a29edcdebe5"
                    },
                    "room": {
                        "aliases": [
                            "Room No."
                        ],
                        "description": "The room number where the specific assignment takes place.\nLabels: Room No.",
                        "placement": {
                            "look_for": "the label 'Room No.'",
                            "placement_description": "Located in the header information block at the top of the page.",
                            "placement_tier": "standalone",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_a5f9c76335c1"
                    },
                    "student_group": {
                        "description": "The specific batch or group of students assigned to the session, especially for parallel practicals.",
                        "placement": {
                            "instance_group": "lab_group_row",
                            "look_for": "the group labels (e.g., A1, A2, B1, C1) in the lab section table",
                            "placement_description": "The first column of the laboratory/practical assignment table at the bottom of the page.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_786bf1b8a85c"
                    },
                    "group": {
                        "aliases": [
                            "A1",
                            "A2",
                            "A3",
                            "B1",
                            "B2",
                            "B3",
                            "C1",
                            "C2",
                            "C3"
                        ],
                        "description": "The short identifier for the student group or batch.\nLabels: A1, A2, A3, B1, B2, B3, C1, C2, C3",
                        "placement": {
                            "ambiguity_resolve": "first_row",
                            "instance_group": "group_assignments",
                            "look_for": "the column headers above the laboratory and project assignments",
                            "placement_description": "The column headers in the laboratory/project assignment tables at the bottom of the page.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_fbb58e3c991b"
                    },
                    "subject": {
                        "description": "The subject or activity scheduled for the slot.",
                        "placement": {
                            "look_for": "the cells within the timetable grid",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_1fbe05699eb6"
                    },
                    "slot_type": {
                        "description": "The nature of the time slot, such as a class period, short break, or lunch break.",
                        "placement": {
                            "instance_group": "timetable_slot",
                            "look_for": "text like 'SHORT BREAK' or 'LUNCH BREAK' within the grid",
                            "placement_description": "The descriptive text for non-instructional slots within the timetable grid.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_74577e59ef41"
                    }
                },
                "type": "object"
            },
            "type": "array",
            "x-field-id": "fld_d5e55dc4b376"
        },
        "faculty_allocation_table": {
            "description": "A table where each row represents the allocation of faculty to a specific subject or practical group.",
            "items": {
                "properties": {
                    "subject_code": {
                        "aliases": [
                            "Sub Code"
                        ],
                        "description": "The unique alphanumeric code of the subject in the allocation row.\nLabels: Sub Code",
                        "placement": {
                            "ambiguity_resolve": "first_row",
                            "instance_group": "subject_list_row",
                            "look_for": "the 'Sub Code' column in the subject list table",
                            "placement_description": "The first column of the subject mapping table located below the timetable grid.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_b5a068601a89"
                    },
                    "subject_name": {
                        "aliases": [
                            "Subject"
                        ],
                        "description": "The full name of the subject in the allocation row.\nLabels: Subject",
                        "placement": {
                            "ambiguity_resolve": "first_row",
                            "instance_group": "subject_list_row",
                            "look_for": "the 'Subject' column in the subject list table",
                            "placement_description": "The second column of the subject mapping table located below the timetable grid.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_6b510f506c72"
                    },
                    "main_faculty": {
                        "aliases": [
                            "Faculty/Sign"
                        ],
                        "description": "The primary faculty member responsible for the subject.\nLabels: Faculty/Sign",
                        "placement": {
                            "ambiguity_resolve": "first_row",
                            "instance_group": "subject_list_row",
                            "look_for": "the 'Faculty/Sign' column in the subject list table",
                            "placement_description": "The third column of the subject mapping table located below the timetable grid.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_2759917cea47"
                    },
                    "practical_group_faculty": {
                        "description": "The faculty member assigned to a specific student group for practical sessions.",
                        "placement": {
                            "instance_group": "lab_group_row",
                            "look_for": "the faculty names listed in the lab section table corresponding to a group",
                            "placement_description": "The cells in the lab assignment table to the right of the student group labels.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_cb59400a5875"
                    },
                    "all_faculty_names": {
                        "aliases": [
                            "Faculty/Sign"
                        ],
                        "description": "A list of all faculty names associated with the subject, including those for practicals.\nLabels: Faculty/Sign",
                        "placement": {
                            "instance_group": "subject_list_row",
                            "look_for": "the list of names in the 'Faculty/Sign' column or lab table",
                            "placement_description": "The faculty column in the subject list or the faculty cells in the lab table.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_3607c2c6a6ad"
                    },
                    "assigned_subjects": {
                        "description": "The list of subjects assigned to a specific teacher.",
                        "placement": {
                            "instance_group": "faculty_list",
                            "look_for": "the subjects aligned with a specific faculty name in the subject list",
                            "placement_description": "The subject names associated with a specific teacher in the mapping tables.",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_9ad8b4bf4cda"
                    }
                },
                "type": "object"
            },
            "type": "array",
            "x-field-id": "fld_70d4580fce31"
        },
        "department_and_academic_information": {
            "description": "A table where each row represents the general academic metadata for a specific class timetable page.",
            "items": {
                "properties": {
                    "department": {
                        "aliases": [
                            "DEPARTMENT OF ARTIFICIAL INTELLIGENCE & DATA SCIENCE"
                        ],
                        "description": "The academic department overseeing the course for this page.\nLabels: DEPARTMENT OF ARTIFICIAL INTELLIGENCE & DATA SCIENCE",
                        "placement": {
                            "look_for": "the top-most header of the page",
                            "placement_tier": "document_summary",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_1ca1a296bdf6"
                    },
                    "class": {
                        "aliases": [
                            "Class"
                        ],
                        "description": "The semester and section identifier for the students on this page.\nLabels: Class",
                        "placement": {
                            "look_for": "the label 'Class' in the header block",
                            "placement_tier": "document_summary",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_f11c889e35d0"
                    },
                    "room_no": {
                        "aliases": [
                            "Room No."
                        ],
                        "description": "The classroom number where the sessions are held for this page.\nLabels: Room No.",
                        "placement": {
                            "look_for": "the label 'Room No.' in the header block",
                            "placement_tier": "document_summary",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_ecf1aad14052"
                    },
                    "class_teacher": {
                        "aliases": [
                            "Class Teacher"
                        ],
                        "description": "The name of the faculty member assigned as the class teacher for this page.\nLabels: Class Teacher",
                        "placement": {
                            "look_for": "the label 'Class Teacher' in the header block",
                            "placement_tier": "document_summary",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_ecfdd9fc7b36"
                    },
                    "session": {
                        "aliases": [
                            "Session"
                        ],
                        "description": "The academic year for the current session on this page.\nLabels: Session",
                        "placement": {
                            "look_for": "the label 'Session' in the header block",
                            "placement_tier": "document_summary",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_7dbad5f697ce"
                    },
                    "page_number": {
                        "description": "The page number of the original document where this information was found.",
                        "placement": {
                            "look_for": "the page number printed on the page",
                            "placement_description": "The page indicator for the document.",
                            "placement_tier": "standalone",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_859fe66643f2"
                    },
                    "issue": {
                        "description": "A description of any ambiguity or warning encountered during extraction.",
                        "placement": {
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_0f231f0e4bec"
                    }
                },
                "type": "object"
            },
            "placement": {
                "look_for": "the header block at the top of each class page",
                "placement_description": "The top header section of each page containing administrative class details.",
                "placement_tier": "document_summary",
                "section": "DEPARTMENT OF ARTIFICIAL INTELLIGENCE & DATA SCIENCE"
            },
            "type": "array",
            "x-field-id": "fld_5ddaa9332c70"
        },
        "practical_and_laboratory_group_allocations": {
            "description": "A table where each row represents the mapping of a laboratory course to a student group and a faculty member.",
            "items": {
                "properties": {
                    "lab_code": {
                        "description": "The code for the laboratory course.",
                        "placement": {
                            "look_for": "the first column of the lab allocation table",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_f3f88598e1d8"
                    },
                    "lab_name": {
                        "description": "The full name of the laboratory course.",
                        "placement": {
                            "look_for": "the second column of the lab allocation table",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_aee08ea2bb3f"
                    },
                    "group": {
                        "description": "The student group identifier assigned to the lab.",
                        "placement": {
                            "look_for": "the column headers above the faculty names in the lab table",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_ea33bba71f01"
                    },
                    "faculty": {
                        "description": "The faculty member assigned to the specific group in the lab.",
                        "placement": {
                            "look_for": "the cells within the lab allocation grid",
                            "placement_tier": "repeated_instance",
                            "section": None
                        },
                        "type": "string",
                        "x-field-id": "fld_f3104704a17e"
                    }
                },
                "type": "object"
            },
            "placement": {
                "ambiguity_resolve": "prefer_detail",
                "detail_section": True,
                "instance_group": "lab_allocation",
                "look_for": "the table at the bottom of the page listing lab codes and group-based faculty",
                "placement_description": "The final table on each page detailing laboratory group assignments.",
                "placement_tier": "document_detail",
                "section": "Events"
            },
            "type": "array",
            "x-field-id": "fld_fae61580a0a2"
        }
    },
    "type": "object"
}
