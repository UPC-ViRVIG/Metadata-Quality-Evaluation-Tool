"""
models/dataset_context.py
-------------------------
The dataset as a metric sees it during evaluation.

The engine builds one context per dataset and passes it to every metric,
which keeps metric implementations free of any knowledge about loading,
caching, or scope filtering.

Both the scoped graph and the unfiltered one are carried, so a metric can
compute against the user's selection while still consulting the full
graph where that is genuinely needed.

Options chosen for this dataset travel here too, keyed by metric id,
because the same metric can be configured differently per dataset.
"""


class DatasetContext:
    """
    Class representing a dataset during evaluation.
    Properties:
    - dataset identifier
    - dataset label
    - RDF graph loaded from the data source
    - scope
    - per-metric options, keyed by metric id
    """
    def __init__(self, dataset_id, label, graph, scope=None, full_graph=None,
                 options=None):
        self.dataset_id = dataset_id
        self.label = label
        self.graph = graph          
        self.scope = scope
        self.full_graph = full_graph or graph
        self.options = options or {}