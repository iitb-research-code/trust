# -*- coding: utf-8 -*-

from __future__ import print_function

import pandas as pd
import os

DB_dir = 'database'
DB_csv = 'data.csv'


class Database(object):

  def __init__(self, dir="database", csv="data.csv"):
    if dir is not None:
      self.DB_dir = dir
    if csv is not None:
      self.DB_csv = csv
    self._gen_csv()
    self.data = pd.read_csv(self.DB_csv)
    self.classes = set(self.data["cls"])

  def _gen_csv(self):
    if os.path.exists(self.DB_csv):
      return
    with open(self.DB_csv, 'w', encoding='UTF-8') as f:
      f.write("img,cls")
      for root, _, files in os.walk(self.DB_dir, topdown=False):
        cls = root.split('/')[-1]
        for name in files:
          if not name.endswith('.jpg'):
            continue
          img = os.path.join(root, name)
          f.write("\n{},{}".format(img, cls))

  def __len__(self):
    return len(self.data)

  def get_class(self):
    return self.classes

  def get_data(self):
     return self.data


if __name__ == "__main__":
  db = Database()
  data = db.get_data()
  classes = db.get_class()
  print(len(data))
  print("DB length:", len(db))
  print(classes)
