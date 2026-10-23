// MongoDB store (the "M" in MERN). Used when MONGO_URI is set.
import mongoose from 'mongoose';

const opts = { strict: false, timestamps: true, minimize: false };
const Dataset = mongoose.model('Dataset', new mongoose.Schema({ _id: { type: String }, name: String, files: [mongoose.Schema.Types.Mixed] }, opts));
const Job = mongoose.model('Job', new mongoose.Schema({
  _id: { type: String }, datasetId: { type: String, index: true }, status: String, mapping: mongoose.Schema.Types.Mixed,
  params: mongoose.Schema.Types.Mixed, result: mongoose.Schema.Types.Mixed, error: String,
}, opts));

const out = (d) => {
  if (!d) return null;
  const o = d.toObject ? d.toObject() : d;
  const { _id, __v, ...rest } = o;
  return { id: _id, ...rest, createdAt: o.createdAt?.toISOString?.() ?? o.createdAt, updatedAt: o.updatedAt?.toISOString?.() ?? o.updatedAt };
};

function collection(Model) {
  return {
    async create({ id, ...rest }) { return out(await Model.create({ _id: id, ...rest })); },
    async get(id) { return out(await Model.findById(id).lean()); },
    async update(id, patch) { return out(await Model.findByIdAndUpdate(id, { $set: patch }, { new: true, strict: false }).lean()); },
    async remove(id) { await Model.deleteOne({ _id: id }); },
    async list(filter = {}) { return (await Model.find(filter).sort({ createdAt: -1 }).lean()).map(out); },
  };
}

export async function createMongoStore(uri) {
  await mongoose.connect(uri, { serverSelectionTimeoutMS: 5000 });
  await Job.updateMany({ status: { $in: ['queued', 'running'] } }, { $set: { status: 'failed', error: 'Server restarted' } });
  return { kind: 'mongodb', datasets: collection(Dataset), jobs: collection(Job), close: () => mongoose.disconnect() };
}
