---
title: IDS Edge batching fault troubleshooting
domain: ids-edge-batching
system: IDS Edge Integrated Batching
knowledge_role: troubleshooting
source: Batching Integration Errors.docx.txt
last_verified: 2025-06
confidence: operator-provided
---

# IDS Edge batching fault troubleshooting

These entries are symptom-to-action records from the supplied batching support data. Preserve the exact fault text when escalating. “Abort the batch” should be followed only when it is safe and allowed by the plant procedure.

## Water (RM) is taking in manual but not in auto

### Question variants

- Water is entering manually but not automatically.
- Water RM is not dosing in auto mode.
- Water auto feed is not working.

### Resolution

Abort the running batch, request the data push from IT, and then contact the IDS helpline.

## Gate overloaded fault

### Question variants

- Gate overloaded fault.
- The gate overload alarm is showing during batching.

### Resolution

Abort the running batch, request the data push from IT, check the mix design, and take a fresh load according to the approved plant procedure.

## Ticket is in use and cannot be deleted

### Question variants

- Event Viewer says a ticket is in use and cannot be deleted.
- Error: `Ticket ... Is in use. Cannot delete.`

### Meaning and resolution

This means the batch has already started, so the ticket cannot be deleted. Complete the batch according to the approved process.

## Mixer not ready fault

### Question variants

- Mixer not ready fault.
- Mixer is not ready in HMI.
- `Mixer not ready` appears before batching.

### Resolution

Check that the previous batch was completed properly. Confirm that all required controls are on and in Auto mode on the HMI.

## PLC is not connected

### Question variants

- PLC is not getting connected.
- IDS cannot connect to the PLC.
- The batching PLC is offline.

### Resolution

Check connectivity using the plant-approved ping procedure. The supplied source gives the example `ping 192.168.1.190 -t`; use the actual configured PLC address for the plant. If the PLC does not respond, inspect the PLC network cable for damage and escalate if required.

## IDS does not open

### Question variants

- IDS is not opening.
- IDS Edge will not start.
- The IDS application does not launch.

### Resolution

Check whether MySQL is running in Windows Services. If it is running and IDS still does not open, contact the IDS helpline.

## Cement filling fault

### Question variants

- Cement filling fault is showing.
- SIR cement filling fault.
- Cement silo filling failed.

### Resolution

Abort the running batch and verify that the correct SILO is assigned to the material/product before starting a fresh load.

## Admixture dosing is higher than target

### Question variants

- Admixture dosing is more than target.
- Admixture is overdosing.
- Chemical admixture quantity is too high in the batch.

### Resolution

Abort the batch and update the design in ERP. Do not compensate by guessing a manual dosage change; verify the approved mix design and plant settings.

## Data record fault

### Question variants

- Data record fault during batching.
- The data record error appeared while running a batch.

### Meaning and resolution

The supplied source attributes this fault to the PLC disconnecting for a fraction of a second during the batch. Abort the batch and start a fresh load according to the approved plant procedure.

## IDS touch panel or HMI error

### Question variants

- IDS touch panel is showing an error.
- HMI is displaying an IDS fault.
- Touch panel error during batching.

### Resolution

Contact the IDS helpline and preserve the exact HMI message, timestamp and affected batch details.
