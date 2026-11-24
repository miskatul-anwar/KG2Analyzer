import { api } from "@/api/client";

type Writable = { write: (b: Blob) => Promise<void>; close: () => Promise<void> };
type FileHandle = { createWritable: () => Promise<Writable> };
type DirHandle = {
  name: string;
  getFileHandle: (n: string, o: { create: boolean }) => Promise<FileHandle>;
  getDirectoryHandle: (n: string, o: { create: boolean }) => Promise<DirHandle>;
};
type FsWindow = Window & { showDirectoryPicker?: (o?: { mode?: string; id?: string }) => Promise<DirHandle> };

const fetchBlob = async (url: string) => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`download failed (${r.status})`);
  return r.blob();
};
const isAbort = (e: unknown) => e instanceof DOMException && e.name === "AbortError";

function download(url: string, name: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/** Write `files` (paths like `retail/fact_classes/<cube>/mdkg_dataset.nq`) into a folder the user picks. */
async function writeTree(paths: string[]): Promise<string | null> {
  const w = window as FsWindow;
  try {
    const root = await w.showDirectoryPicker!({ mode: "readwrite", id: "kg2a-mdkgs" });
    for (const path of paths) {
      const parts = path.split("/");
      let dir = root;
      for (const d of parts.slice(0, -1)) dir = await dir.getDirectoryHandle(d, { create: true });
      const out = await (await dir.getFileHandle(parts[parts.length - 1], { create: true })).createWritable();
      await out.write(await fetchBlob(api.mdkgFileUrl(path)));
      await out.close();
    }
    return root.name;
  } catch (e) {
    if (isAbort(e)) return null;
    throw e;
  }
}

/**
 * Save every built MDKG where the user chooses, exactly as KG2MD writes it: one folder per KG
 * (`<kg>/fact_classes/<cube>/mdkg_schema.ttl · mdkg_data.ttl · mdkg_dataset.nq`, `factclass_selection.json`,
 * `kg2md.log`) plus `identity.ttl`. Without a folder picker (non-Chromium browsers) it downloads `mdkg.zip`.
 * Returns where the files went, or null if the user cancelled.
 */
export async function saveAllMdkgs(kgs: string[]): Promise<string | null> {
  if (!(window as FsWindow).showDirectoryPicker) {
    download(api.mdkgZipUrl(), "mdkg.zip");
    return "downloaded mdkg.zip";
  }
  const { files } = await api.mdkgFiles();
  const where = await writeTree(files.map((f) => f.path));
  return where === null ? null : `saved ${kgs.length} MDKG folder${kgs.length === 1 ? "" : "s"} + identity.ttl to “${where}”`;
}

/** Save one KG's MDKG folder into a folder the user picks (or download the zip). */
export async function saveOneMdkg(kg: string): Promise<string | null> {
  if (!(window as FsWindow).showDirectoryPicker) {
    download(api.mdkgZipUrl(), "mdkg.zip");
    return "downloaded mdkg.zip";
  }
  const { files } = await api.mdkgFiles(kg);
  const where = await writeTree(files.map((f) => f.path));
  return where === null ? null : `saved ${kg}/ to “${where}”`;
}
