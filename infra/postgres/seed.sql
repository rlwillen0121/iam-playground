-- Groups for enterprise-small-v1. Inserted only when lab_meta has no row.
-- This file does not insert scim_users. A restart must not reseed them.
INSERT INTO scim_groups (id, app_id, display_name, external_id)
SELECT id, app_id, display_name, NULL
FROM (VALUES
    ('a80685e9-97a2-5f8e-bf85-697e5b090659'::uuid, 'app-a', 'Readers'),
    ('c2f28d72-284c-5d0a-8522-89737ce607d0'::uuid, 'app-a', 'Administrators'),
    ('d34b4637-1ec3-53b4-8d50-10e195f862ec'::uuid, 'app-a', 'Editors'),
    ('22083feb-8db2-54f1-a40f-9e6b3a9f6c3b'::uuid, 'app-a', 'Auditors'),
    ('25f00d29-996d-51c7-b57b-9757fb2b2a0d'::uuid, 'app-a', 'Engineering'),
    ('14c2daea-e020-5621-819f-6fc89c2cff67'::uuid, 'app-a', 'Sales'),
    ('41d4f5e4-c5f5-52f9-aa70-c8c08d30cd64'::uuid, 'app-a', 'Support'),
    ('d889fe8b-a47e-5100-9f38-44c31d32c968'::uuid, 'app-a', 'Finance'),
    ('30164e5c-9ffc-5376-9057-4c5b1dd29339'::uuid, 'app-a', 'Contractors'),
    ('1e4ca750-5865-52da-af03-013efda27341'::uuid, 'app-a', 'Operators'),
    ('0a2cb128-d1cc-509e-a6a9-2e7056f6029b'::uuid, 'app-a', 'Viewers'),
    ('912d2ed2-6fd0-5ead-9d11-ae9fee99d802'::uuid, 'app-a', 'Billing'),
    ('af587148-cf15-509e-8b68-4fe4906b4c46'::uuid, 'app-b', 'Readers'),
    ('f2501855-1e09-5e69-af6b-697bb668fda1'::uuid, 'app-b', 'Administrators'),
    ('00aea5be-d459-59de-afe9-fe7c31c3402a'::uuid, 'app-b', 'Editors'),
    ('271a6f6f-3629-5349-bd9e-66b8ca010ea7'::uuid, 'app-b', 'Auditors'),
    ('54186507-0142-502b-ac47-4c836ff986a9'::uuid, 'app-b', 'Engineering'),
    ('aa494d82-d4e8-5b03-86b4-4960ee607c7c'::uuid, 'app-b', 'Sales'),
    ('f757fcdf-4dbd-5692-bf92-e8c64b995fa7'::uuid, 'app-b', 'Support'),
    ('60d504b6-1a15-5323-b8f4-a1ebfe1b719b'::uuid, 'app-b', 'Finance'),
    ('6cce0761-9945-5679-bf10-2472c9a2d715'::uuid, 'app-b', 'Contractors'),
    ('9682e415-1c84-5d88-828c-6db2cb49b0d1'::uuid, 'app-b', 'Operators'),
    ('39ba3eee-29a2-57cb-a9c8-fcc95b67576a'::uuid, 'app-b', 'Viewers'),
    ('69f3fd26-ce0d-5991-a0fc-af40f09b58ee'::uuid, 'app-b', 'Billing')
) AS seed(id, app_id, display_name)
WHERE NOT EXISTS (SELECT 1 FROM lab_meta);

INSERT INTO lab_meta (generation, fixture_id, seeded_at, accepting)
SELECT 1, 'enterprise-small-v1', now(), true
WHERE NOT EXISTS (SELECT 1 FROM lab_meta);
