import { api } from "@/api/client";

type DirHandle = { getFileHandle: (n: string, o: { create: boolean }) => Promise<FileHandle> };
type FileHandle = { createWritable: () => Promise<{ write: (b: Blob) => Promise<void>; close: () => Promise<void> }> };
type FsWindow = Window & {
  showDirectoryPicker?: (o?: { mode?: string; id?: string }) => Promise<DirHandle & { name: string }>;
  showSaveFilePicker?: (o?: { suggestedName?: string; id?: string }) => Promise<FileHandle & { name: string }>;
};

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

/**
 * Save every built MDKG where the user chooses: a folder picker writes `<kg>.mdkg.trig` + `identity.ttl`
 * (File System Access API, Chromium); other browsers download `mdkg.zip`.
 * Returns a short description of where the files went, or null if the user cancelled.
 */
export async function saveAllMdkgs(kgs: string[]): Promise<string | null> {
  const w = window as FsWindow;
  if (!w.showDirectoryPicker) {
    download(api.mdkgZipUrl(), "mdkg.zip");
    return "downloaded mdkg.zip";
  }
  try {
    const dir = await w.showDirectoryPicker({ mode: "readwrite", id: "kg2a-mdkgs" });
    const write = async (name: string, blob: Blob) => {
      const fh = await dir.getFileHandle(name, { create: true });
      const out = await fh.createWritable();
      await out.write(blob);
      await out.close();
    };
    for (const kg of kgs) await write(`${kg}.mdkg.trig`, await fetchBlob(api.mdkgFileUrl(kg)));
    await write("identity.ttl", await fetchBlob(api.identityUrl()));
    return `saved ${kgs.length} MDKG file${kgs.length === 1 ? "" : "s"} + identity.ttl to “${dir.name}”`;
  } catch (e) {
    if (isAbort(e)) return null;
    throw e;
  }
}

/** Save one MDKG with a native "Save as…" dialog where available, else download it. */
export async function saveOneMdkg(kg: string): Promise<string | null> {
  const w = window as FsWindow;
  const name = `${kg}.mdkg.trig`;
  if (!w.showSaveFilePicker) {
    download(api.mdkgFileUrl(kg), name);
    return `downloaded ${name}`;
  }
  try {
    const fh = await w.showSaveFilePicker({ suggestedName: name, id: "kg2a-mdkg" });
    const out = await fh.createWritable();
    await out.write(await fetchBlob(api.mdkgFileUrl(kg)));
    await out.close();
    return `saved ${fh.name}`;
  } catch (e) {
    if (isAbort(e)) return null;
    throw e;
  }
}
