// The five detector layers (PRD CLEAN-15, `detectors/base.py` LAYERS), shallowest first: each looks at a
// wider part of the data than the one before. Which checks a layer holds comes from the catalog.
export const LAYERS: { name: string; looks: string }[] = [
  { name: "Surface", looks: "single values" },
  { name: "Columns", looks: "each column as a whole" },
  { name: "Records", looks: "rows against rows" },
  { name: "Relationships", looks: "columns against columns" },
  { name: "Meaning", looks: "the dataset as a whole" },
];
