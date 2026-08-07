---
title: IDS and Oracle ERP integration troubleshooting
domain: ids-edge-oracle-erp
system: IDS Edge Integrated Batching and Oracle ERP
knowledge_role: troubleshooting
source: Title Ticket Not Showing or Reaching Knowledge.txt; Batching Integration Errors.docx.txt
last_verified: 2025-06
confidence: operator-provided
---

# IDS and Oracle ERP integration troubleshooting

Use these entries for tickets, mix designs, material codes, Sales Orders, ERP-to-IDS synchronization, services and integration reports. The actions below are the supplied operator guidance; verify local approvals and plant policy before changing production data.

## New mix design or FG code does not appear in IDS

### Question variants

- The new mix design is not showing in IDS.
- The FG code is missing from IDS.
- ERP design and IDS design are different.
- Ticket is submitted in ERP but not visible in IDS.

### Resolution

Update the mix design again in ERP to re-push it to IDS. If the ticket still does not appear, check that the IDS RDC Import Live Service is running, confirm that all material codes used by the mix design exist in IDS, and inspect the Event Viewer for the integration error.

## IDS RDC Import Live Service is stopped

### Question variants

- IDS RDC Import Live Service is off.
- The IDS import service is not running.
- The ticket is not reaching IDS because the service stopped.

### Resolution

1. Click the Windows Search Bar and type `Services`.
2. Open the Services application.
3. Click any service and press the letter `I` to locate the IDS services.
4. Locate `IDS RDC Import Live Service`.
5. Click `Restart`.

After the restart, re-check the mix-design/ticket flow and inspect the Event Viewer if the issue persists.

Reference guide: https://youtu.be/h8qkN_VA2nw

## Material codes in the mix design do not exist in IDS

### Question variants

- A material code is missing in IDS.
- Please add FAMSAND code in IoT/IDS.
- The mix design material is not visible in IDS.
- How do I add a raw material code?

### Resolution

1. Open `QC Control`.
2. Select `Materials`.
3. Click the `+` add button.
4. Enter the material code exactly as it exists in ERP.
5. Enter the material name exactly as it exists in ERP.
6. Select the appropriate Family Code.
7. Click `Save`.
8. If required by the plant configuration, assign the material to the correct BIN/SILO in `ConfigBOM`.

All material codes used by a mix design must exist in IDS before the ticket can appear. Confirm the ERP code, name, family and physical assignment before re-pushing the mix design.

## Raw material details are not visible in an ERP Sales Order

### Question variants

- Raw material details are missing in the ERP SO.
- The ERP Sales Order does not show material details.
- What should I check when the SO has no raw material details?

### Resolution

Update the mix design in ERP and confirm that the VPN and required services are running. If the details still do not appear, capture the Event Viewer error and escalate to the integration/support team.

## Final submission is not happening or invoice cannot be printed

### Question variants

- Final submission is failing.
- I cannot print the invoice.
- The batch is complete but the final submission is not reflected.

### Resolution

Check Event Viewer and the `RDC Online Batch Data Report` in ERP. If the data is not present in that report, post the incident in the Integration forum according to the local support process.

## VPN is not connecting

### Question variants

- VPN is not connecting.
- ERP/IDS integration is unavailable because VPN is down.
- The plant cannot reach the ERP service.

### Resolution

Contact the IT helpdesk. Do not invent a VPN configuration change or bypass the approved network support process.

## A submitted ticket was deleted and a new Sales Order was raised

### Question variants

- I deleted a ticket that had not reached IDS and raised it again.
- The SO is blocked after deleting the ticket.
- The new SO is showing but the old one is blocked.

### Resolution

If deletion was attempted before the ticket reached IDS, the Sales Order may become blocked. Use a new Sales Order according to the approved ERP/IDS process. Record the old ticket/SO identifiers for support investigation.

## ERP design and IDS design do not match

### Question variants

- ERP design and IDS design are different.
- Mix design is updated in ERP but IDS still has old data.
- The ERP design is not syncing to IDS.

### Resolution

Update the design in ERP and confirm that the IDS service is running and the VPN is connected. If it still does not synchronize, inspect Event Viewer and escalate with the design, ticket and error details.
