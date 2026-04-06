export interface Author {
  family: string;
  given: string;
}

export interface Entry {
  id: string;
  type: string;
  title: string;
  author: Author[];
  doi?: string;
  isbn?: string;
  date?: string;
  journal?: string;
  volume?: string;
  issue?: string;
  pages?: string;
  publisher?: string;
  abstract?: string;
  tags: string[];
  collections: string[];
  url?: string;
  files: string[];
  added?: string;
  modified?: string;
}

export interface Collection {
  id: string;
  name: string;
  parent_id: string | null;
  color?: string | null;
  created?: string;
  children: Collection[];
}
