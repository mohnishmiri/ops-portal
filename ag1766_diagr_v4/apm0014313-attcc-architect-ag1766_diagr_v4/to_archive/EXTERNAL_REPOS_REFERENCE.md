# External Repositories Reference Guide

**For:** Next developer/agent team  
**Purpose:** Quick reference for reusing code from `drawpyo-main` and `multicloud-diagrams-main`

---

## Repository 1: drawpyo-main

**Location:** `docs/drawpyo-main/`  
**License:** MIT ✅  
**Purpose:** Python library for programmatic draw.io diagram creation

### Quick Facts

- **Language:** Python
- **Lines of Code:** ~2,500 total
- **Key Classes:** `Diagram`, `File`, `Object`, `Vertex`, `Edge`, `Group`
- **Strengths:** Parent-child nesting, style inheritance, tree layout, round-trip editing
- **Weaknesses:** Generates diagrams from scratch (not mutation-based)

### Files to Reuse

| File | Lines | What It Does | How to Use |
|---|---|---|---|
| `drawpyo/objects/base.py` | 200+ | Base object model, parent-child relationships | Reference for container nesting |
| `drawpyo/objects/shapes.py` | 300+ | Vertex, Edge, Group, Container primitives | Reference for cell generation |
| `drawpyo/diagram.py` | 400+ | Diagram/page management, XML serialization | Reference for XML generation |
| `drawpyo/style.py` | 250+ | TOML-based style database | Reference for style registry design |
| `drawpyo/layout/tree.py` | 180+ | Tree layout algorithm | Adapt for grid layout |
| `drawpyo/parser.py` | 200+ | XML parsing, round-trip import/export | Reference for future editing UI |

### Code Snippets to Adapt

#### 1. Parent-Child Cell Nesting

**From:** `drawpyo/objects/shapes.py` Group class

```python
class Group(Vertex):
    """Container for child objects"""
    def __init__(self, label, children=None, **kwargs):
        super().__init__(label, **kwargs)
        self.children = children or []
        self.vertex = True
    
    def add_child(self, obj):
        self.children.append(obj)
        obj.parent = self
```

**How HAF Uses It:**
- `_generate_subcells()` creates child cells inside region containers
- Each interface is a child cell with parent = region container

---

#### 2. Deterministic ID Generation

**From:** `drawpyo/base.py` `_generate_id()` method

```python
import hashlib

def _generate_id(content):
    """Generate deterministic ID from content"""
    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

**How HAF Uses It:**
- `_generate_subcells()` uses `hashlib.sha256()` for stable IDs
- Same input always produces same ID

---

#### 3. XML Serialization Pattern

**From:** `drawpyo/diagram.py` `xml` property

```python
@property
def xml(self):
    """Generate mxGraphModel XML"""
    root = ET.Element('mxGraphModel')
    diagram = ET.SubElement(root, 'diagram')
    
    for cell in self.cells:
        ET.SubElement(diagram, 'mxCell', {
            'id': cell.id,
            'value': cell.value,
            'style': cell.style,
            'parent': cell.parent,
            'vertex': str(cell.vertex).lower()
        })
    
    return ET.tostring(root, encoding='unicode')
```

**How HAF Uses It:**
- `haf_pipeline.py` generates mxCell elements directly
- Uses same XML structure as drawpyo

---

#### 4. Style Database Pattern

**From:** `drawpyo/style.py` TOML loader

```python
import toml

class StyleDatabase:
    def __init__(self, toml_file):
        self.styles = toml.load(toml_file)
    
    def get_style(self, category, name):
        return self.styles[category][name]
    
    def apply_style(self, obj, category, name):
        style = self.get_style(category, name)
        obj.style = style
```

**How HAF Adapted It:**
- `haf_styles.py` uses JSON instead of TOML
- `load_interface_styles()` loads cloud provider icons
- `get_style()` retrieves style by key

---

#### 5. Tree Layout Algorithm

**From:** `drawpyo/layout/tree.py`

```python
def layout_tree(root, x=0, y=0, h_spacing=100, v_spacing=100):
    """Hierarchical tree layout"""
    root.x = x
    root.y = y
    
    children = root.children
    total_width = len(children) * h_spacing
    start_x = x - total_width / 2
    
    for i, child in enumerate(children):
        child.x = start_x + i * h_spacing
        child.y = y + v_spacing
        layout_tree(child, child.x, child.y, h_spacing, v_spacing)
```

**How HAF Could Use It:**
- Adapt for grid layout instead of tree
- Use for hierarchical topology diagrams
- Improve spacing and alignment

---

### Integration Checklist

- ✅ Parent-child nesting — Already implemented in HAF
- ✅ Deterministic IDs — Already implemented in HAF
- ✅ XML serialization — Already implemented in HAF
- ✅ Style database — Already adapted in HAF (JSON)
- 🔄 Tree layout — Could improve grid layout (Phase 3)
- 📋 Round-trip editing — Future enhancement (Phase 4)

---

## Repository 2: multicloud-diagrams-main

**Location:** `docs/multicloud-diagrams-main/`  
**License:** MIT ✅  
**Purpose:** Generate cloud topology diagrams with provider-specific icons

### Quick Facts

- **Language:** Python
- **Lines of Code:** ~900 total
- **Key Function:** `MulticloudDiagram` class
- **Strengths:** Cloud provider icons, grid layout, deterministic IDs
- **Weaknesses:** Generates from scratch (not mutation-based)

### Files to Reuse

| File | Lines | What It Does | How to Use |
|---|---|---|---|
| `multicloud_diagrams.py` | 872 | Core diagram generation | Reference for cell/edge generation |
| `aws_provider.json` | 45 icons | AWS service styles | **DIRECTLY IMPORT** |
| `azure_provider.json` | 38 icons | Azure service styles | **DIRECTLY IMPORT** |
| `gcp_provider.json` | 28 icons | GCP service styles | **DIRECTLY IMPORT** (Phase 3) |
| `generic_provider.json` | 15 icons | Generic shapes | **DIRECTLY IMPORT** |

### Cloud Provider Icons Available

#### AWS (45 icons)

**Compute:**
- EC2, Lambda, ECS, EKS, **Outpost** ✅, Batch, Lightsail

**Storage:**
- S3, EBS, EFS, Glacier, Storage Gateway, Backup

**Database:**
- RDS, DynamoDB, ElastiCache, Redshift, Neptune, DocumentDB

**Network:**
- VPC, Route 53, CloudFront, Direct Connect, VPN, Elastic Load Balancer

**Management:**
- CloudWatch, CloudFormation, Systems Manager, OpsWorks

**Security:**
- IAM, KMS, Secrets Manager, WAF, Shield, ACM

**Analytics:**
- Athena, EMR, Kinesis, SageMaker, QuickSight

**Integration:**
- SQS, SNS, EventBridge, Step Functions, AppFlow

#### Azure (38 icons)

**Compute:**
- Virtual Machines, App Service, Container Instances, Kubernetes Service, Batch

**Storage:**
- Blob Storage, File Share, Data Lake, Archive, Backup

**Database:**
- SQL Database, Cosmos DB, MySQL, PostgreSQL, MariaDB

**Network:**
- Virtual Network, Load Balancer, Application Gateway, VPN Gateway, ExpressRoute

**Management:**
- Monitor, Automation, Log Analytics, Advisor

**Security:**
- Key Vault, Azure AD, DDoS Protection, Firewall

**Analytics:**
- Synapse, Data Factory, Stream Analytics, Databricks

**Integration:**
- Service Bus, Event Grid, Logic Apps, API Management

#### GCP (28 icons)

**Compute:**
- Compute Engine, App Engine, Cloud Functions, GKE, Cloud Run

**Storage:**
- Cloud Storage, Firestore, Datastore, Cloud SQL

**Database:**
- BigQuery, Cloud Spanner, Memorystore, Cloud Bigtable

**Network:**
- VPC, Cloud Load Balancing, Cloud CDN, Cloud Interconnect

**Management:**
- Cloud Monitoring, Cloud Logging, Cloud Deployment Manager

**Security:**
- Cloud IAM, Cloud KMS, Cloud Armor

**Analytics:**
- Dataflow, Dataproc, BigQuery ML, Looker

### Code Snippets to Adapt

#### 1. Vertex Generation with Provider Icons

**From:** `multicloud_diagrams.py` `add_vertex()` method

```python
def add_vertex(self, name, provider, service_type, x=0, y=0, width=80, height=80):
    """Add vertex with provider-specific style"""
    style = self.get_provider_style(provider, service_type)
    
    cell = {
        'id': f'{provider}_{service_type}_{len(self.vertices)}',
        'value': name,
        'style': style,
        'vertex': 1,
        'x': x,
        'y': y,
        'width': width,
        'height': height
    }
    
    self.vertices.append(cell)
    return cell['id']

def get_provider_style(self, provider, service_type):
    """Get style from provider JSON"""
    return self.provider_styles[provider][service_type]
```

**How HAF Could Use It:**
- Apply AWS/Azure icons to interface region cells
- Use provider-specific styling
- Already partially implemented in `haf_styles.py`

---

#### 2. Edge Generation with Labels

**From:** `multicloud_diagrams.py` `add_edge()` method

```python
def add_edge(self, source_id, target_id, label='', protocol='', style=''):
    """Add edge with label"""
    edge = {
        'id': f'edge_{len(self.edges)}',
        'value': label,
        'style': style or 'edgeStyle=orthogonalEdgeStyle',
        'edge': 1,
        'parent': 1,
        'source': source_id,
        'target': target_id
    }
    
    if protocol:
        edge['protocol'] = protocol
    
    self.edges.append(edge)
    return edge['id']
```

**How HAF Uses It:**
- `_generate_edges()` creates edges between interface cells
- Adds labels with protocol information

---

#### 3. Grid/Table Layout Algorithm

**From:** `multicloud_diagrams.py` `distribute_vertices()` method

```python
def distribute_vertices(self, layout_type='grid', cols=None):
    """Distribute vertices in grid/table layout"""
    if layout_type == 'grid':
        cols = cols or int(len(self.vertices) ** 0.5)
        rows = (len(self.vertices) + cols - 1) // cols
        
        for i, vertex in enumerate(self.vertices):
            row = i // cols
            col = i % cols
            vertex['x'] = col * 150
            vertex['y'] = row * 150
```

**How HAF Uses It:**
- `_generate_subcells()` implements adaptive grid layout
- Auto-adjusts columns based on entry count
- Respects container geometry

---

#### 4. Provider Style JSON Format

**From:** `aws_provider.json`

```json
{
  "ec2": "shape=mxgraph.aws4.ec2;fillColor=#FF9900;strokeColor=#232F3E;...",
  "lambda": "shape=mxgraph.aws4.lambda;fillColor=#FF9900;strokeColor=#232F3E;...",
  "rds": "shape=mxgraph.aws4.rds;fillColor=#527FFF;strokeColor=#232F3E;...",
  "outpost": "shape=mxgraph.aws4.outpost;fillColor=#FF9900;strokeColor=#232F3E;..."
}
```

**How HAF Uses It:**
- Directly imported into `interface_styles.json`
- Applied to generated cells via `style` attribute

---

#### 5. Deterministic Composite IDs

**From:** `multicloud_diagrams.py` ID generation

```python
def generate_id(provider, service, index):
    """Generate deterministic composite ID"""
    return f'{provider}_{service}_{index}'
```

**How HAF Uses It:**
- `_generate_subcells()` uses hash-based IDs
- Same input always produces same ID
- Enables meaningful diffs

---

### Integration Checklist

- ✅ AWS icons — Already integrated in `interface_styles.json`
- ✅ Azure icons — Already integrated in `interface_styles.json`
- 🔄 GCP icons — Can be integrated in Phase 3
- ✅ Style format — Already in use in HAF
- ✅ Grid layout — Already adapted in HAF
- ✅ Deterministic IDs — Already implemented in HAF
- ✅ Vertex/edge generation — Already implemented in HAF

---

## Quick Copy-Paste: Cloud Provider Icons

### AWS Icons (Ready to Use)

```json
{
  "ec2": "shape=mxgraph.aws4.ec2;fillColor=#FF9900;strokeColor=#232F3E;fontColor=#232F3E",
  "lambda": "shape=mxgraph.aws4.lambda;fillColor=#FF9900;strokeColor=#232F3E;fontColor=#232F3E",
  "rds": "shape=mxgraph.aws4.rds;fillColor=#527FFF;strokeColor=#232F3E;fontColor=#232F3E",
  "s3": "shape=mxgraph.aws4.s3;fillColor=#569A31;strokeColor=#232F3E;fontColor=#232F3E",
  "vpc": "shape=mxgraph.aws4.vpc;fillColor=#FF9900;strokeColor=#232F3E;fontColor=#232F3E",
  "route53": "shape=mxgraph.aws4.route_53;fillColor=#FF9900;strokeColor=#232F3E;fontColor=#232F3E",
  "outpost": "shape=mxgraph.aws4.outpost;fillColor=#FF9900;strokeColor=#232F3E;fontColor=#232F3E"
}
```

### Azure Icons (Ready to Use)

```json
{
  "vm": "shape=mxgraph.azure.virtual_machine;fillColor=#0078D4;strokeColor=#005A9E;fontColor=#FFFFFF",
  "app_service": "shape=mxgraph.azure.app_service;fillColor=#0078D4;strokeColor=#005A9E;fontColor=#FFFFFF",
  "sql_db": "shape=mxgraph.azure.sql_database;fillColor=#0078D4;strokeColor=#005A9E;fontColor=#FFFFFF",
  "vnet": "shape=mxgraph.azure.virtual_network;fillColor=#0078D4;strokeColor=#005A9E;fontColor=#FFFFFF",
  "storage": "shape=mxgraph.azure.storage;fillColor=#0078D4;strokeColor=#005A9E;fontColor=#FFFFFF"
}
```

---

## How to Reuse Code

### Step 1: Copy JSON Files

```bash
# Copy AWS icons
cp docs/multicloud-diagrams-main/aws_provider.json \
   src/migration_intake/topology/config/haf_styles/aws_icons.json

# Copy Azure icons
cp docs/multicloud-diagrams-main/azure_provider.json \
   src/migration_intake/topology/config/haf_styles/azure_icons.json

# Copy GCP icons (Phase 3)
cp docs/multicloud-diagrams-main/gcp_provider.json \
   src/migration_intake/topology/config/haf_styles/gcp_icons.json
```

### Step 2: Update Style Registry

```python
# In haf_styles.py
def load_interface_styles():
    styles = {}
    
    # Load AWS icons
    with open('config/haf_styles/aws_icons.json') as f:
        styles['aws'] = json.load(f)
    
    # Load Azure icons
    with open('config/haf_styles/azure_icons.json') as f:
        styles['azure'] = json.load(f)
    
    return styles
```

### Step 3: Apply to Generated Cells

```python
# In _generate_subcells()
style = get_style(location, 'default')  # Get AWS/Azure style
cell['style'] = style
```

---

## Formatting and Diagram Details

### Recommended Improvements (Phase 2+)

1. **Icon Sizing**
   - AWS: 40x40 pixels for interface cells
   - Azure: 40x40 pixels for interface cells
   - GCP: 40x40 pixels for interface cells

2. **Color Coding**
   - AWS: Orange (#FF9900)
   - Azure: Blue (#0078D4)
   - GCP: Red (#EA4335)
   - Midrange: Gray (#808080)
   - Unknown: Light Gray (#CCCCCC)

3. **Label Positioning**
   - Icons: Top-left of cell
   - Labels: Below icon, centered
   - Font: Arial, 10pt, bold

4. **Spacing**
   - Cell width: 120 pixels
   - Cell height: 80 pixels
   - Column spacing: 20 pixels
   - Row spacing: 20 pixels

5. **Edge Styling**
   - Orthogonal routing
   - Rounded corners
   - Protocol labels (SSH, HTTPS, SQL, etc.)
   - Color-coded by protocol

---

## Summary

**What to Copy:**
- ✅ AWS/Azure/GCP icon JSON files
- ✅ Style string format
- ✅ Grid layout algorithm
- ✅ Vertex/edge generation patterns

**What to Reference:**
- 📖 Tree layout algorithm (for Phase 3)
- 📖 Round-trip editing (for Phase 4)
- 📖 Performance optimization techniques

**What's Already Done in HAF:**
- ✅ XML security hardening
- ✅ Deterministic ID generation
- ✅ Grid layout with adaptive columns
- ✅ Sub-cell generation
- ✅ Edge generation
- ✅ Style registry

---

**Next Steps:** See `HANDOFF_SUMMARY.md` for Phase 2 implementation roadmap
