---
title: IDS Edge configuration and batching guides
domain: ids-edge
system: IDS Edge Integrated Batching
knowledge_role: operator-guide
source: Youtube Video Description and Link for Batching Query errors.txt
last_verified: 2025-06
confidence: source-provided
---

# IDS Edge configuration and batching guides

These entries describe IDS Edge batching operations for RDC Ready-Mix/Dry-Mix plants. The source material is a guide index with reference videos. Where the source does not provide screen-by-screen steps, do not infer them; use the linked approved guide.

## Add a manually fed raw material

### Question variants

- How do I add a manually fed raw material in IDS Edge?
- How do I configure hand-fed material in the skip bucket, aggregate conveyor or mixer?
- How do I add UTLFNE, FIBRE, FIBREPE, MSILICA or EPSTB?

### When this applies

Manual feeding means the material is added by an operator directly into the skip bucket, aggregate conveyor or mixer without a conveyor, motor, screw conveyor or weighing scale controlling that feed.

### Source examples

The source lists UTLFNE (Ultra Fine), FIBRE, FIBREPE (Fibre Polyethylene), MSILICA (Micro Silica), and EPSTB (EPS beads/stabilizer) as examples. These are examples, not a universal plant rule. Verify the actual equipment and plant configuration before selecting manual feed.

### Resolution

The supplied source describes the correct use case but does not include the complete screen-by-screen configuration. Follow the approved reference guide rather than guessing a menu path.

Reference video: https://youtu.be/CIi0asOp05o

## Add an automatically fed raw material

### Question variants

- How do I add an automatic-feed material in IDS Edge?
- How do I configure cement, fly ash, water, admixture or aggregate for auto feed?
- How do I add a material connected to a conveyor, screw conveyor, motor or scale?

### When this applies

Automatic feeding means the material is dispensed by equipment such as a conveyor, motor, screw conveyor or weighing scale during batching, without manual intervention for the feed.

### Source examples

The source lists CEMENT, FLYASH, ULTRAFINE, FIBRE, WATER, ADMIXTURE and AGGREGATE as examples. FIBRE may be manual or automatic depending on the configured plant equipment; do not assume the feed mode from the material name alone.

### Resolution

The supplied source describes the correct use case but does not include the complete screen-by-screen configuration. Follow the approved reference guide rather than guessing a menu path.

Reference video: https://youtu.be/JAD-kWQn0qg

## Assign or change a BIN/SILO for a product

### Question variants

- How do I assign a BIN or SILO to a mix design in IDS Edge?
- How do I change the cement silo, water weigher, admixture jar or aggregate bin?
- The product is mapped to the wrong physical storage unit. What should I check?

### Resolution

Each raw material used in a mix design must be mapped to its corresponding physical storage or dispensing unit before batching. The source examples are cement to a cement silo, water to a water weigher, admixture to an admixture jar, and aggregate to aggregate bins.

The supplied source does not contain the complete screen-by-screen procedure. Use the approved reference guide and verify the assignment against the actual plant equipment and mix design before starting a batch.

Reference video: https://youtu.be/2I-9SzQfkz4

## Run two BINs/SILOs simultaneously: coarse feeding or parallel feed

### Question variants

- How do I run two silos at the same time?
- How do I activate two BINs simultaneously?
- What is coarse feeding or parallel feeding in IDS Edge?
- How can I reduce cement feeding time using two silos?

### Operational meaning

Coarse Feeding, Parallel Feed, and simultaneous BIN/SILO feeding refer to feeding two storage or dispensing units for the same material at the same time. The source gives two cement silos as the example. The intended benefit is lower feeding time per batch and higher throughput when the plant configuration supports it.

### Control boundary

Do not assume that every plant can safely use parallel feed or that any two silos can be combined. Confirm the material mapping, equipment interlocks, weighing behavior and approved plant procedure. The supplied text does not provide the configuration steps or operating limits; follow the approved guide.

Reference video: https://youtu.be/bYw09ubvZtM

## Use Event Viewer for batching troubleshooting

### Question variants

- How do I check Event Viewer for an IDS batching error?
- Where can I find the IDS error log?
- What should I check first when batching behaves unexpectedly?

### Purpose

Windows Event Viewer records system and application events, warnings and errors. The source identifies it as the first diagnostic tool when an RDC batching issue, unexpected behavior or failure occurs.

### Resolution

Open Event Viewer on the plant PC and inspect the relevant IDS/application errors around the time of the incident. Record the exact error text, ticket number, timestamp and affected batch before escalating. The supplied source does not specify a complete Event Viewer navigation procedure; do not invent one.

Reference video: https://youtu.be/04HNO5LzhoU

## Add a new unused Sales Order in IDS Edge while ERP is offline

### Question variants

- How do I add an unused SO when ERP is offline?
- Can I manually enter a new Sales Order in IDS Edge?
- What approval is required for offline Sales Order entry?

### Required control

Head Office (HO) approval must be obtained before adding a Sales Order in offline mode. This is a sensitive operation because the ERP is unavailable and the order is being entered outside the normal workflow.

### Resolution

Use the approved offline Sales Order procedure only after confirming that the Sales Order is newly created and unused and after receiving HO approval. The supplied source does not contain complete screen-by-screen steps. Never bypass the approval requirement.

Reference video: https://youtu.be/bqPcZrr9MSU

## IDS Edge service: start or restart

### Question variants

- What is the IDS Edge service?
- IDS Edge is not responding. How do I check the service?
- How do I start or restart the IDS service?

### Operational meaning

The IDS Edge service is a Windows background process required for batching operations. If it is stopped, IDS Edge may not function correctly.

### Resolution

Check whether the IDS Edge service is running. Start or restart it using the approved local procedure when required. The source provides the related service reference video but does not define every service name or recovery condition; do not guess a service name if the operator's screen differs.

Reference video: https://youtu.be/h8qkN_VA2nw
