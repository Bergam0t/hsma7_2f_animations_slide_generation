import simpy
from sim_tools.distributions import Exponential, Lognormal
import pandas as pd
import math
from scipy import stats
import random
import numpy as np
from vidigi.logging import EventLogger, TrialLogger
from vidigi.utils import create_event_position_df, EventPosition
from vidigi.prep import reshape_for_animations, generate_animation_df  # NEW
from vidigi.animation import generate_animation  # NEW/UPDATED
from vidigi.resources import VidigiPriorityStore, VidigiStore  # NEW/UPDATED
from vidigi.process_mapping import (
    add_sim_timestamp,
    discover_dfg,
    dfg_to_graphviz,
    dfg_to_cytoscape,
)
from IPython.display import display

POSSIBLE_DISEASES = [
    "Mogwai's Hydrophobia",
    "Jurassic Fever",
    "Xenomorphian Dyspepsia",
    "Temporal Displacement Disorder",
    "Stay-Puft Oedema",
    "Truman's Paranoia",
    "Gumpian Restless Leg Syndrome",
]


class Patient:
    def __init__(self, p_id, priority, disease):
        self.id = p_id
        self.q_time_registration = pd.NA
        self.q_time_nurse = pd.NA
        self.q_time_specialist = pd.NA
        self.priority = priority
        self.disease = disease


class Param:
    def __init__(
        self,
        mean_patient_inter=3,
        mean_registration_time=3,
        sd_registration_time=2,
        mean_nurse_consult_time=10,
        sd_nurse_consult_time=5,
        mean_specialist_time=60,
        sd_specialist_time=20,
        num_receptionists=1,
        num_nurses=2,
        num_specialists=1,
        specialist_prob=0.3,
        sim_duration=60 * 12,
        num_replications=5,
    ):
        self.mean_patient_inter = mean_patient_inter
        self.mean_registration_time = mean_registration_time
        self.sd_registration_time = sd_registration_time
        self.mean_nurse_consult_time = mean_nurse_consult_time
        self.sd_nurse_consult_time = sd_nurse_consult_time
        self.mean_specialist_time = mean_specialist_time
        self.sd_specialist_time = sd_specialist_time
        self.num_receptionists = num_receptionists
        self.num_nurses = num_nurses
        self.num_specialists = num_specialists
        self.specialist_prob = specialist_prob
        self.sim_duration = sim_duration
        self.num_replications = num_replications


class Model:
    def __init__(self, param, replication_id):
        self.param = param
        self.replication_id = replication_id
        self.env = simpy.Environment()
        self.patient_counter = 0

        self.receptionist = VidigiStore(
            self.env,
            num_resources=self.param.num_receptionists,
        )
        self.nurse = VidigiPriorityStore(
            self.env,
            num_resources=self.param.num_nurses,
        )

        self.specialist = VidigiPriorityStore(
            self.env,
            num_resources=self.param.num_specialists,
        )

        ss = np.random.SeedSequence(self.replication_id)
        seeds = ss.spawn(8)
        self.patient_inter_dist = Exponential(
            mean=self.param.mean_patient_inter, random_seed=seeds[0]
        )
        self.registration_time_dist = Lognormal(
            mean=self.param.mean_registration_time,
            stdev=self.param.sd_registration_time,
            random_seed=seeds[2],
        )
        self.nurse_consult_time_dist = Lognormal(
            mean=self.param.mean_nurse_consult_time,
            stdev=self.param.sd_nurse_consult_time,
            random_seed=seeds[1],
        )

        self.specialist_branch_prob_rng = np.random.default_rng(seeds[3])

        self.specialist_time_dist = Lognormal(
            mean=self.param.mean_specialist_time,
            stdev=self.param.sd_specialist_time,
            random_seed=seeds[4],
        )

        self.patient_priority_rng = np.random.default_rng(seeds[6])

        self.patient_disease = np.random.default_rng(seeds[7])

        self.list_of_patients = []
        self.mean_q_time_registration = pd.NA
        self.sd_q_time_registration = pd.NA
        self.perc_90_q_time_registration = pd.NA
        self.mean_q_time_nurse = pd.NA
        self.sd_q_time_nurse = pd.NA
        self.perc_90_q_time_nurse = pd.NA
        self.mean_q_time_specialist = pd.NA
        self.sd_q_time_specialist = pd.NA
        self.perc_90_q_time_specialist = pd.NA

        self.logger = EventLogger(env=self.env, run_number=self.replication_id)

    def generator_patient_arrivals(self):
        while True:
            self.patient_counter += 1

            pat_pri_ran_gen = self.patient_priority_rng.random()

            if pat_pri_ran_gen < 0.2:
                patient_priority = 1
            elif pat_pri_ran_gen < 0.4:
                patient_priority = 2
            elif pat_pri_ran_gen < 0.7:
                patient_priority = 3
            else:
                patient_priority = 4

            disease = self.patient_disease.choice(POSSIBLE_DISEASES)

            p = Patient(self.patient_counter, patient_priority, disease)

            self.list_of_patients.append(p)
            self.env.process(self.attend_clinic(p))
            sampled_inter = self.patient_inter_dist.sample()
            yield self.env.timeout(sampled_inter)

    def attend_clinic(self, patient):
        self.logger.log_arrival(entity_id=patient.id, priority=patient.priority)
        start_q_registration = self.env.now
        self.logger.log_queue(
            entity_id=patient.id,
            event="receptionist_wait_begins",
            priority=patient.priority,  # NEW
        )

        with self.receptionist.request() as req:
            receptionist_obtained = yield req
            end_q_registration = self.env.now
            patient.q_time_registration = end_q_registration - start_q_registration
            self.logger.log_resource_use_start(
                entity_id=patient.id,
                event="being_seen_by_receptionist",
                resource_id=receptionist_obtained.id_attribute,
                priority=patient.priority,  # NEW
            )
            sampled_reg_act_time = self.registration_time_dist.sample()
            yield self.env.timeout(sampled_reg_act_time)
            self.logger.log_resource_use_end(
                entity_id=patient.id,
                event="receptionist_visit_ends",
                resource_id=receptionist_obtained.id_attribute,
                priority=patient.priority,  # NEW
            )

        start_q_nurse = self.env.now
        self.logger.log_queue(
            entity_id=patient.id,
            event="nurse_wait_begins",
            priority=patient.priority,  # NEW
        )

        with self.nurse.request(priority=patient.priority) as req:
            nurse_obtained = yield req
            end_q_nurse = self.env.now
            patient.q_time_nurse = end_q_nurse - start_q_nurse
            self.logger.log_resource_use_start(
                entity_id=patient.id,
                event="being_seen_by_nurse",
                resource_id=nurse_obtained.id_attribute,
                priority=patient.priority,  # NEW
            )
            sampled_nurse_act_time = self.nurse_consult_time_dist.sample()
            yield self.env.timeout(sampled_nurse_act_time)
            self.logger.log_resource_use_end(
                entity_id=patient.id,
                event="nurse_treatment_ends",
                resource_id=nurse_obtained.id_attribute,
                priority=patient.priority,  # NEW
            )

        if self.specialist_branch_prob_rng.random() < self.param.specialist_prob:
            start_q_specialist = self.env.now
            self.logger.log_queue(
                entity_id=patient.id,
                event="specialist_wait_begins",
                priority=patient.priority,  # NEW
            )

            with self.specialist.request(priority=patient.priority) as req:
                specialist_obtained = yield req
                end_q_specialist = self.env.now
                patient.q_time_specialist = end_q_specialist - start_q_specialist
                self.logger.log_resource_use_start(
                    entity_id=patient.id,
                    event="being_seen_by_specialist",
                    resource_id=specialist_obtained.id_attribute,
                    priority=patient.priority,  # NEW
                )
                sampled_specialist_act_time = self.specialist_time_dist.sample()
                yield self.env.timeout(sampled_specialist_act_time)
                self.logger.log_resource_use_end(
                    entity_id=patient.id,
                    event="specialist_treatment_ends",
                    resource_id=specialist_obtained.id_attribute,
                    priority=patient.priority,  # NEW
                )

        self.logger.log_departure(
            entity_id=patient.id,
            priority=patient.priority,  # NEW
        )

    def run_model(self):
        self.env.process(self.generator_patient_arrivals())
        self.env.run(until=self.param.sim_duration)

    def convert_entity_list_to_dataframe(self, entity_list):
        entity_dateframe = pd.DataFrame(entity.__dict__ for entity in entity_list)

        return entity_dateframe

    def calculate_run_results(self, entity_dataframe):
        self.mean_q_time_registration = entity_dataframe["q_time_registration"].mean()
        self.sd_q_time_registration = entity_dataframe["q_time_registration"].std()
        self.perc_90_q_time_registration = entity_dataframe[
            "q_time_registration"
        ].quantile(0.9)

        self.mean_q_time_nurse = entity_dataframe["q_time_nurse"].mean()
        self.sd_q_time_nurse = entity_dataframe["q_time_nurse"].std()
        self.perc_90_q_time_nurse = entity_dataframe["q_time_nurse"].quantile(0.9)

        self.mean_q_time_specialist = entity_dataframe["q_time_specialist"].mean()
        self.sd_q_time_specialist = entity_dataframe["q_time_specialist"].std()
        self.perc_90_q_time_specialist = entity_dataframe["q_time_specialist"].quantile(
            0.9
        )

    def get_vidigi_event_log(self):
        return self.logger.to_dataframe()


class Trial:
    def __init__(self, param):
        self.param = param
        self.list_of_simulation_replications = []
        self.trial_mean_q_time_registration = pd.NA
        self.trial_sd_q_time_registration = pd.NA
        self.trial_perc_90_q_time_registration = pd.NA
        self.trial_mean_q_time_nurse = pd.NA
        self.trial_sd_q_time_nurse = pd.NA
        self.trial_perc_90_q_time_nurse = pd.NA
        self.trial_mean_q_time_specialist = pd.NA
        self.trial_sd_q_time_specialist = pd.NA
        self.trial_perc_90_q_time_specialist = pd.NA
        self.ci_lower_q_time_registration = pd.NA
        self.ci_upper_q_time_registration = pd.NA
        self.se_q_time_registration = pd.NA
        self.ci_lower_q_time_nurse = pd.NA
        self.ci_upper_q_time_nurse = pd.NA
        self.se_q_time_nurse = pd.NA
        self.ci_lower_q_time_specialist = pd.NA
        self.ci_upper_q_time_specialist = pd.NA
        self.se_q_time_specialist = pd.NA

        self.trial_logger = TrialLogger()

    def run_trial(self):
        for replication_id in range(self.param.num_replications):
            model_replication = Model(self.param, replication_id)
            model_replication.run_model()
            patient_df = model_replication.convert_entity_list_to_dataframe(
                model_replication.list_of_patients
            )
            model_replication.calculate_run_results(patient_df)
            self.list_of_simulation_replications.append(model_replication)

            self.trial_logger.add_log(model_replication.logger)

    def calculate_trial_results(self):
        self.replication_df = pd.DataFrame(
            replication.__dict__ for replication in self.list_of_simulation_replications
        )

        self.trial_mean_q_time_registration = self.replication_df[
            "mean_q_time_registration"
        ].mean()
        self.trial_sd_q_time_registration = self.replication_df[
            "mean_q_time_registration"
        ].std()
        self.trial_perc_90_q_time_registration = self.replication_df[
            "mean_q_time_registration"
        ].quantile(0.9)

        self.trial_mean_q_time_nurse = self.replication_df["mean_q_time_nurse"].mean()
        self.trial_sd_q_time_nurse = self.replication_df["mean_q_time_nurse"].std()
        self.trial_perc_90_q_time_nurse = self.replication_df[
            "mean_q_time_nurse"
        ].quantile(0.9)

        self.trial_mean_q_time_specialist = self.replication_df[
            "mean_q_time_specialist"
        ].mean()
        self.trial_sd_q_time_specialist = self.replication_df[
            "mean_q_time_specialist"
        ].std()
        self.trial_perc_90_q_time_specialist = self.replication_df[
            "mean_q_time_specialist"
        ].quantile(0.9)

        self.se_q_time_registration = self.trial_sd_q_time_registration / math.sqrt(
            self.param.num_replications
        )
        self.se_q_time_nurse = self.trial_sd_q_time_nurse / math.sqrt(
            self.param.num_replications
        )

        self.se_q_time_specialist = self.trial_sd_q_time_specialist / math.sqrt(
            self.param.num_replications
        )

        t = stats.t.ppf(0.975, df=self.param.num_replications - 1)

        self.ci_lower_q_time_registration = self.trial_mean_q_time_registration - (
            t * self.se_q_time_registration
        )
        self.ci_upper_q_time_registration = self.trial_mean_q_time_registration + (
            t * self.se_q_time_registration
        )

        self.ci_lower_q_time_nurse = self.trial_mean_q_time_nurse - (
            t * self.se_q_time_nurse
        )
        self.ci_upper_q_time_nurse = self.trial_mean_q_time_nurse + (
            t * self.se_q_time_nurse
        )

        self.ci_lower_q_time_specialist = self.trial_mean_q_time_specialist - (
            t * self.se_q_time_specialist
        )
        self.ci_upper_q_time_specialist = self.trial_mean_q_time_specialist + (
            t * self.se_q_time_specialist
        )


class Animation:
    def __init__(self, event_log, params):
        self.event_log = event_log
        self.params = params

        self.layout = create_event_position_df(
            [
                EventPosition(event="arrival", x=0, y=850, label="Entrance"),
                EventPosition(
                    event="receptionist_wait_begins",
                    x=200,
                    y=800,
                    label="Waiting for Receptionist",
                ),
                EventPosition(
                    event="being_seen_by_receptionist",
                    x=200,
                    y=700,
                    label="Being Seen By Receptionist",
                    resource="num_receptionists",
                ),
                EventPosition(
                    event="nurse_wait_begins", x=200, y=550, label="Waiting for Nurse"
                ),
                EventPosition(
                    event="being_seen_by_nurse",
                    x=200,
                    y=450,
                    label="Being Seen By Nurse",
                    resource="num_nurses",
                ),
                EventPosition(
                    event="specialist_wait_begins",
                    x=200,
                    y=300,
                    label="Waiting for Specialist",
                ),
                EventPosition(
                    event="being_seen_by_specialist",
                    x=200,
                    y=200,
                    label="Being Seen By Specialist",
                    resource="num_specialists",
                ),
                EventPosition(event="depart", x=200, y=50, label="Exit"),
            ]
        )

    def build_animation(self, time_interval=1):
        reshaped_df = reshape_for_animations(
            event_log=self.event_log,
            every_x_time_units=time_interval,
            limit_duration=self.params.sim_duration,
        )

        animation_df = generate_animation_df(
            full_entity_df=reshaped_df,
            event_position_df=self.layout,
        )

        def show_priority_icon(row):
            # First check this isn't a '+ y more' row
            if "more" not in row["icon"]:
                if row["priority"] == 1:
                    return "🔴"
                if row["priority"] == 2:
                    return "🟠"
                if row["priority"] == 3:
                    return "🟡"
                if row["priority"] == 4:
                    return "🔵"
                else:
                    return row["icon"]
            else:
                return row["icon"]

        animation_df = animation_df.assign(
            icon=animation_df.apply(show_priority_icon, axis=1)
        )

        return generate_animation(
            full_entity_df_plus_pos=animation_df,
            event_position_df=self.layout,
            scenario=self.params,
            plotly_height=600,
            plotly_width=1100,
            entity_icon_size=16,
        )


class ProcessMap:
    def __init__(self, event_log, params):
        self.event_log = event_log
        self.params = params

    def build_process_map(self, priority="all", interactive=False):  # NEW/UPDATED
        # First, we take our event log and add a timestamp column to it, as it's required
        # so that it can display average durations accurately
        my_event_log_timestamp = add_sim_timestamp(
            self.event_log, time_unit="minutes", sim_start="09:00:00"
        ).copy()

        # NEW
        # We'll filter if priority isn't 'all' (the default)
        if priority != "all":
            my_event_log_timestamp = my_event_log_timestamp[
                my_event_log_timestamp["priority"] == priority
            ]
        # END NEW

        # Now we'll discover the pathways in the model
        nodes, edges = discover_dfg(my_event_log_timestamp)

        if interactive:
            # An an interactive version
            cytoscape_widget = dfg_to_cytoscape(
                nodes,
                edges,
                min_frequency=5,
                spacing_factor=2,
                width=1400,
            )
            display(cytoscape_widget)

        else:
            # Now we can create a static representation of flow through the process
            graphviz_graph = dfg_to_graphviz(
                nodes,
                edges,
                min_frequency=5,
                title=f"Priority: {priority}",  # NEW
            )
            display(graphviz_graph)


if __name__ == "__main__":
    base_case_params = Param()
    base_case_trial = Trial(base_case_params)
    base_case_trial.run_trial()
    base_case_trial.calculate_trial_results()

    print("BASE CASE TRIAL RESULTS")
    print("-----------------------")
    print("Queuing Time for Registration")
    print(f"Mean : {base_case_trial.trial_mean_q_time_registration:.2f} minutes")
    print(f"SD : {base_case_trial.trial_sd_q_time_registration:.2f} minutes")
    print(
        f"90th Perc : {base_case_trial.trial_perc_90_q_time_registration:.2f}",
        "minutes",
    )
    print(f"Standard Error : {base_case_trial.se_q_time_registration:.2f}")
    print(
        f"95% CI : ({base_case_trial.ci_lower_q_time_registration:.2f}, ",
        f"{base_case_trial.ci_upper_q_time_registration:.2f}) minutes",
    )
    print()

    print("Queuing Time for the Nurse")
    print(f"Mean : {base_case_trial.trial_mean_q_time_nurse:.2f} minutes")
    print(f"SD : {base_case_trial.trial_sd_q_time_nurse:.2f} minutes")
    print(f"90th Perc : {base_case_trial.trial_perc_90_q_time_nurse:.2f} minutes")
    print(f"Standard Error : {base_case_trial.se_q_time_nurse:.2f}")
    print(
        f"95% CI : ({base_case_trial.ci_lower_q_time_nurse:.2f}, ",
        f"{base_case_trial.ci_upper_q_time_nurse:.2f}) minutes",
    )
    print()

    print("Queuing Time for the Specialist")
    print(f"Mean : {base_case_trial.trial_mean_q_time_specialist:.2f} minutes")
    print(f"SD : {base_case_trial.trial_sd_q_time_specialist:.2f} minutes")
    print(
        f"90th Perc : {base_case_trial.trial_perc_90_q_time_specialist:.2f} ", "minutes"
    )
    print(f"Standard Error : {base_case_trial.se_q_time_specialist:.2f}")
    print(
        f"95% CI : ({base_case_trial.ci_lower_q_time_specialist:.2f}, ",
        f"{base_case_trial.ci_upper_q_time_specialist:.2f}) minutes",
    )
    print()

    my_event_log = base_case_trial.trial_logger.get_log_by_run(run=0, as_df=True)
    my_animation = Animation(my_event_log, base_case_params)
    fig = my_animation.build_animation()
    fig.show()

    # NEW
    my_process_map = ProcessMap(my_event_log, base_case_params)

    for priority in range(1, 5):
        my_process_map.build_process_map(priority=priority)
