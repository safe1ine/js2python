import { join } from 'path';
import fs from 'fs';

export default function load(file) {
  const full = join(process.cwd(), file);
  return fs.readFileSync(full, 'utf-8');
}
