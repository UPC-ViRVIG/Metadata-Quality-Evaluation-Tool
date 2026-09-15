class DatasetContext:
    """
    Class representing a dataset during evaluation.
    """

    def __init__(
        self,
        dataset_id,
        label,
        graph,
        scope=None,
        full_graph=None,
        config=None,
    ):
        self.dataset_id = dataset_id
        self.label = label
        self.graph = graph
        self.scope = scope
        self.full_graph = full_graph or graph
        self.config = config or {}
