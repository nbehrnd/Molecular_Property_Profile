"""Generates data for molecular property profiling.

Starts with tabular molecular property data, one molecule per line.

For each feature requested, generate a collection_pb2.Descriptor
proto and write that to a file.

Those files are then consumed by plot_collections.py
"""

import sys

from typing import Dict

from absl import app
from absl import flags
from absl import logging

from google.protobuf import text_format

import numpy as np
import pandas as pd

from scipy import stats

import collection_pb2

# The max number of values that will be written
_MAX_FLOAT_POINTS = 100

FLAGS = flags.FLAGS

flags.DEFINE_list('feature_names', [], "Name of feature(s) to process")
flags.DEFINE_string('feature_descriptions', None, 'File containing feature descriptions')
flags.DEFINE_string('collection', "", "name for the collection generating this data (Chembl...)")
flags.DEFINE_string('color', "black", "Line color when this collection is plotted")
flags.DEFINE_string('stem', "MPP", "name stem for files produced")
flags.DEFINE_string('sep', " ", "Input token separator, default space")
flags.DEFINE_boolean('verbose', False, "verbose output")

quantiles = [0.01, 0.05, 0.10, 0.50, 0.90, 0.95, 0.99]

def usage(ret):
  sys.exit(ret)

def determine_median(proto):
  """Set proto.median based on proto.quantile.

  Args:
  """
  proto.median = proto.quantile[3].value

def update_description(proto, collection: str,
                       feature_name:str,
                       feature_descriptions: Dict[str, str],
                       line_color: str):
  """based on `name` update the description in `proto`.

  Args:
    proto:
    feature_names:
    feature_descriptions
    line_color:
  """
  proto.description.feature_name = feature_name

  if feature_name in feature_descriptions:
    proto.description.plot_title = feature_descriptions[feature_name]
    proto.description.description = feature_descriptions[feature_name]
  else:
    proto.description.plot_title = feature_name

  proto.description.line_color = line_color
  proto.description.source = collection

def add_quantiles(data: np.array,
                  proto: collection_pb2.Descriptor):
  """Add quantiles from `data` to `proto`.

  Args:
    data:
    proto:
  Returns:
  """
  qvalues = np.quantile(data, quantiles)
  for q, v in zip(quantiles, qvalues):
    value = proto.quantile.add()
    value.quantile = q
    value.value = v

def set_numeric_values(data: np.array,
                       proto) -> None:
  """Update the numeric statistics in `proto` based on `data`.

  Args:
    data:
    proto:
  Returns:
  """
  proto.minval = float(np.min(data))
  proto.maxval = float(np.max(data))
  proto.mean = np.mean(data)
  add_quantiles(data, proto)
  determine_median(proto)

def profile_feature(data:np.array,
                    collection: str,
                    collection_color: str,
                    feature_name: str,
                    feature_descriptions: Dict[str, str],
                    verbose: bool) -> int:
  """Create a collection_pb2.Descriptor from `data`.

  Args:
    data: Raw data points
    collection: name of collection.
    collection_color: color associated with `collection`
    feature_name: name of `data`.
    feature_descriptions: more descriptive feature names
    verbose:
  Returns:
  """
  print(f"Processing {feature_name}")
  if verbose:
    print(feature_name, stats.describe(data))
  result = collection_pb2.Descriptor()
  update_description(result, collection, feature_name, feature_descriptions, collection_color)

  set_numeric_values(data, result)

  unique, counts = np.unique(data, return_counts=True)
  if len(unique) < _MAX_FLOAT_POINTS:
    if data.dtype == np.int64:
      for v,c in zip(unique, counts):
        vc = result.int_values.add()
        vc.value = v
        vc.count = c
    else:
      for v,c in zip(unique, counts):
        vc = result.float_values.add()
        vc.value = v
        vc.count = c
    return result

  hist,bin_edges = np.histogram(data, bins=_MAX_FLOAT_POINTS)
  n = len(hist)
  for i in range(n):
    vc = result.float_values.add()
    vc.value = bin_edges[i]
    vc.count = hist[i]

  return result

def generate_feature_profile(data: pd.DataFrame,
                             collection: str,
                             feature_name: str,
                             feature_descriptions: Dict[str, str],
                             collection_color: str,
                             name_stem: str,
                             verbose: bool):
  """Generate a property profile for `feature_name`.

  Args:
    data: raw data
    feature_name: name of `data`
    feature_descriptions: -> more descriptive feature names
    name_stem: stem for file to be created
    verbose:
  """

  column_number = data.columns.get_loc(feature_name)
  if column_number < 0:
    logging.fatal("No %s in %r", feature_name, data.columns)

  feature_type = data.dtypes[column_number]

  if verbose:
    logging.info("Feature %s found in column %d type %r", feature_name, column_number, feature_type)

  proto = profile_feature(np.array(data[feature_name]), collection,
                         collection_color, feature_name, feature_descriptions, verbose)

  output_fname = f"{name_stem}_{feature_name}.dat"
  with open(output_fname, "w") as writer:
    writer.write(text_format.MessageToString(proto))

def generate_profile(args):
  """Generates collection protos from molecular features.

  Input files are passed in `args`
  """
  verbose = FLAGS.verbose
  collection = FLAGS.collection
  collection_color = FLAGS.color
  name_stem = FLAGS.stem
  sep = FLAGS.sep

  if len(args) == 1:
    logging.error("Must specify input file as argument")
    usage(1)

  if len(collection) == 0:
    logging.error("Must specify the collection name")
    usage(1)

  # The names of the feature(s) we will process.
  feature_name = []
  # feature_descriptions may come from a previously created proto
  feature_descriptions = {}
  # We might get everything we need from a previous run.
  if FLAGS.feature_descriptions is not None:
    with open(FLAGS.feature_descriptions, 'r') as reader:
      as_string = reader.read()
    proto = text_format.Parse(as_string, collection_pb2.Descriptions())
    for fname in proto.feature_to_description:
      feature_descriptions[fname] = proto.feature_to_description[fname].description
      feature_name.append(fname)

  if len(collection_color) == 0:
    collection_color = 'black'

  data = pd.read_csv(args[1], header=0, sep=sep)
  #data.set_index("Name", drop=True, inplace=True)
  if verbose:
    logging.info("Read dataframe with %d rows and %d columns", len(data), len(data.columns))

  if len(feature_name) == 0:
    feature_name = data.columns
  else:
    must_exit = False
    for name in feature_name:
      if not name in data.columns:
        logging.error("Cannot find %s in header", name)
        must_exit = True

    if must_exit:
      sys.exit(1)

  for i, name in enumerate(feature_name):
    generate_feature_profile(data, collection, name, feature_descriptions,
                             collection_color, name_stem, verbose)

if __name__ == "__main__":
  app.run(generate_profile)
