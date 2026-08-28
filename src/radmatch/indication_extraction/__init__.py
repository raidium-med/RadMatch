"""Optional indication extraction — parse the study indication out of a
report and write `<series_uuid>.txt` files that the main pipeline can
inject as context into Stages 1, 2, and 3b.

The pipeline never requires indications; this module is a convenience
preprocessor for datasets where indications are embedded in the report
text under common headers (INDICATION, CLINICAL HISTORY, etc.).
"""

from radmatch.indication_extraction.inference import extract_indications

__all__ = ["extract_indications"]
